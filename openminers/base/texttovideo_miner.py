# The MIT License (MIT)
# Copyright © 2023 Yuma Rao

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

import torch
import argparse
import bittensor

from rich import print
from typing import List, Dict, Union, Tuple
from abc import ABC, abstractmethod

class BaseTextToVideoMiner( bittensor.BaseMinerNeuron, ABC ):

    @classmethod
    @abstractmethod
    def add_args( cls, parser: argparse.ArgumentParser ):
        ...

    @abstractmethod
    def forward( self, text: str, num_inference_steps: int, num_frames: int, fps: int ) -> str:
        ...

    @classmethod
    @abstractmethod
    def check_config( cls, config: 'bittensor.Config' ):
        ...

    @classmethod
    def config( cls ) -> "bittensor.Config":
        parser = argparse.ArgumentParser()
        cls.add_super_args( parser )
        return bittensor.config( parser )

    @classmethod
    def add_super_args( cls, parser: argparse.ArgumentParser ):
        """ Add arguments specific to BasePromptingMiner to parser.
        """
        cls.add_args(parser)

    def __init__( self, config: "bittensor.Config" = None ):
        super( BaseTextToVideoMiner, self ).__init__()

        class Synapse( bittensor.TextToVideoSynapse ):
            def priority( _, forward_call: "bittensor.TextToVideoForwardCall" ) -> float:
                return self.priority( forward_call )
            def blacklist( _, forward_call: "bittensor.TextToVideoForwardCall" ) -> Union[ Tuple[bool, str], bool ]:
                return self.blacklist( forward_call )
            def backward( _, video: bytes, text: str, rewards: torch.FloatTensor ) -> str: pass
            def forward( _, text: str, num_inference_steps: int, num_frames: int, fps: int ) -> bytes:
                return self.forward( text, num_inference_steps, num_frames, fps )
            
        self.synapse = Synapse( axon = self.axon )