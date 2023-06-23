# The MIT License (MIT)
# Copyright © 2021 Yuma Rao

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import time
import torch
import argparse
import openminers
from typing import List, Dict
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
from transformers.deepspeed import HfDeepSpeedConfig
import deepspeed
import os

local_rank = int(os.getenv('LOCAL_RANK', '0'))
world_size = int(os.getenv('WORLD_SIZE', '1'))

class BloomChatMiner( openminers.BasePromptingMiner ):

    @classmethod
    def add_args( cls, parser: argparse.ArgumentParser ):
        parser.add_argument('--deployment_framework',  type=str, choices=['accelerate', 'deepspeed'], default="accelerate", help='Inference framework to use for multi-gpu inference')
        parser.add_argument('--bloom.model_name', type=str, default="sambanovasystems/BLOOMChat-176B-v1", help='Name/path of model to load' )
        parser.add_argument('--bloom.max_new_tokens', type=int, default=100, help='Number of new tokens to generate' )


    def __init__( self, *args, **kwargs):
        super( BloomChatMiner, self ).__init__( *args, **kwargs )
        model_name = "sambanovasystems/BLOOMChat-176B-v1"
        tokenizer = AutoTokenizer.from_pretrained(self.config.bloom.model_name)
        
        if self.config.deployment_framework == "deepspeed":

            os.environ["TOKENIZERS_PARALLELISM"] = "false" # To avoid warnings about parallelism in tokenizers
            self.local_rank = int(os.getenv('LOCAL_RANK', '0'))
            world_size = int(os.getenv('WORLD_SIZE', '1'))
            torch.cuda.set_device(self.local_rank)
            deepspeed.init_distributed()

            self.model = AutoModelForCausalLM.from_pretrained(self.config.bloom.model_name)
            model_hidden_size = self.model.config.hidden_size

            # batch size has to be divisible by world_size, but can be bigger than world_size
            train_batch_size = 1 * world_size

            # ds_config variables
            ds_config = {
                "fp16": {
                    "enabled": False,
                },
                "bf16": {
                    "enabled": False,
                },
                "zero_optimization": {
                    "stage": 3,
                    "overlap_comm": True,
                    "contiguous_gradients": True,
                    "reduce_bucket_size": model_hidden_size * model_hidden_size,
                    "stage3_prefetch_bucket_size": 0.9 * model_hidden_size * model_hidden_size,
                    "stage3_param_persistence_threshold": 10 * model_hidden_size
                },
                "steps_per_print": 2000,
                "train_batch_size": train_batch_size,
                "train_micro_batch_size_per_gpu": 1,
                "wall_clock_breakdown": False
            }

            # next line instructs transformers to partition the model directly over multiple gpus using
            # deepspeed.zero.Init when model's `from_pretrained` method is called.
            #
            # **it has to be run before loading the model AutoModelForSeq2SeqLM.from_pretrained(model_name)**
            #
            # otherwise the model will first be loaded normally and only partitioned at forward time which is
            # less efficient and when there is little CPU RAM may fail
            dschf = HfDeepSpeedConfig(ds_config)

            # initialise deepspeed ZeRO
            self.ds_engine = deepspeed.initialize(model=self.model,
                                            config_params=ds_config,
                                            model_parameters=None,
                                            optimizer=None,
                                            lr_scheduler=None)[0]
            self.ds_engine.module.eval() 

        else:
            # self.model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=torch.float16 )
            # self.pipe = pipeline( "text-generation", self.model, tokenizer=tokenizer, device = local_rank, max_new_tokens = 256 )
            # self.pipe.model = deepspeed.init_inference(self.pipe.model,
            #                                 mp_size=world_size,
            #                                 dtype=getattr(torch, int8),
            #                                 replace_with_kernel_inject=True)
            
            self.model = AutoModelForCausalLM.from_pretrained(self.model_name, device_map="auto", load_in_8bit=True)

            self.pipe = pipeline( 
                "text-generation",
                model=self.model,
                tokenizer=self.tokenizer,
                load_in_8bit=True,
                device_map="auto",
            )

    @staticmethod
    def _process_history( history: List[ Dict[str, str] ] ) -> str:
        processed_history = ''
        for message in history:
            if message['role'] == 'system':
                processed_history += '<human>: ' + message['content'] + '\n'
            if message['role'] == 'assistant':
                processed_history += '<bot>: ' + message['content'] + '\n'
            if message['role'] == 'user':
                processed_history += '<human>: ' + message['content'] + '\n'
        return processed_history

    def forward( self, messages: List[Dict[str, str]]  ) -> str:
        history = self._process_history(messages)

        if self.config.deployment_framework == "deepspeed":
            t_generate_start = time.time()
            inputs = self.tokenizer.encode(history, return_tensors="pt").to(device=self.local_rank)
            with torch.no_grad():
                outputs = self.ds_engine.module.generate(inputs, max_length= 60)
            resp = self.tokenizer.decode(outputs[0], skip_special_tokens=True).replace( str( history ), "")
            print(resp)
            t_generate_span = time.time() - t_generate_start
            print(t_generate_span)
        
        else:
            t_generate_start = time.time()
            resp = self.pipe( 
                history, 
                max_length=200,
                do_sample=True,
                top_k=10,
                num_return_sequences=1,
                eos_token_id=self.tokenizer.eos_token_id, 
            )[0]['generated_text'].split(':')[-1].replace( str( history ), "")
            t_generate_span = time.time() - t_generate_start
            print(resp)
            print(t_generate_span)
        return resp

if __name__ == "__main__":  
    miner = BloomChatMiner()
    miner.run()
    # with miner:
    #     while True:
    #         print ('running...', time.time())
    #         time.sleep(1)