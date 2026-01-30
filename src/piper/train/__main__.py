import logging
import sys
import os
import pathlib
from pathlib import Path
from urllib.parse import urlparse

import torch
from lightning.pytorch.cli import LightningCLI
from lightning.fabric.utilities.cloud_io import get_filesystem

from .vits.dataset import VitsDataModule
from .vits.lightning import VitsModel

_LOGGER = logging.getLogger(__package__)


class VitsLightningCLI(LightningCLI):
    def add_arguments_to_parser(self, parser):
        parser.link_arguments("data.batch_size", "model.batch_size")
        parser.link_arguments("data.num_symbols", "model.num_symbols")
        parser.link_arguments("model.num_speakers", "data.num_speakers")
        parser.link_arguments("model.sample_rate", "data.sample_rate")
        parser.link_arguments("model.filter_length", "data.filter_length")
        parser.link_arguments("model.hop_length", "data.hop_length")
        parser.link_arguments("model.win_length", "data.win_length")
        parser.link_arguments("model.segment_size", "data.segment_size")
    
    def _parse_ckpt_path(self) -> None:
        """If a checkpoint path is given, parse the hyperparameters from the checkpoint and update the config."""
        if not self.config.get("subcommand"):
            return
        ckpt_path = self.config[self.config.subcommand].get("ckpt_path")
        ckpt_path = self.ensure_local_checkpoint(ckpt_path)
        ckpt_path = self.process_checkpoint(ckpt_path, "checkpoint/")
        self.config[self.config.subcommand]["ckpt_path"] = ckpt_path
        if ckpt_path and Path(ckpt_path).is_file():
            ckpt = torch.load(ckpt_path, weights_only=True, map_location="cpu")
            hparams = ckpt.get("hyper_parameters", {})
            hparams.pop("_instantiator", None)
            if not hparams:
                return
            if "_class_path" in hparams:
                hparams = {
                    "class_path": hparams.pop("_class_path"),
                    "dict_kwargs": hparams,
                }
            hparams = {self.config.subcommand: {"model": hparams}}
            try:
                self.config = self.parser.parse_object(hparams, self.config)
            except SystemExit:
                sys.stderr.write("Parsing of ckpt_path hyperparameters failed!\n")
                raise
    
    def ensure_local_checkpoint(self, path):
        if os.path.exists(path):
            return path
        
        checkpoints_dir = "checkpoints"
        filename = os.path.basename(urlparse(path).path)
        os.makedirs(checkpoints_dir, exist_ok=True)
        local_path = os.path.join(checkpoints_dir, filename)

        # If already downloaded, reuse it
        if os.path.isfile(local_path):
            return local_path
        
        # Otherwise download it
        fs = get_filesystem(path)

        with fs.open(path, "rb") as src, open(local_path, "wb") as dst:
            dst.write(src.read())

        return local_path


    def convert_paths(self, obj):
        """Recursively convert Path objects to strings"""
        if isinstance(obj, pathlib.Path):
            return str(obj)
        elif isinstance(obj, dict):
            return {k: self.convert_paths(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return type(obj)(self.convert_paths(item) for item in obj)
        return obj

    def strip_checkpoint_params(self, checkpoint):
        """Remove conflicting hyperparameters from checkpoint"""
        if 'hyper_parameters' not in checkpoint:
            _LOGGER.info("\n⚠ No 'hyper_parameters' key found in checkpoint")
            return checkpoint
        
        _LOGGER.info("\nOriginal hyperparameters:")
        for key, value in checkpoint['hyper_parameters'].items():
            _LOGGER.info(f"  {key}: {value}")
        
        # Keep only essential architecture parameters
        keep_params = [
            'num_symbols', 'num_speakers', 'resblock', 'resblock_kernel_sizes',
            'resblock_dilation_sizes', 'upsample_rates', 'upsample_initial_channel',
            'upsample_kernel_sizes', 'filter_length', 'hop_length', 'win_length',
            'mel_channels', 'mel_fmin', 'mel_fmax', 'inter_channels', 'hidden_channels',
            'filter_channels', 'n_heads', 'n_layers', 'kernel_size', 'p_dropout',
            'n_layers_q', 'use_spectral_norm', 'gin_channels', 'use_sdp', 'segment_size'
        ]
        
        keys_to_remove = [key for key in checkpoint['hyper_parameters'].keys() 
                        if key not in keep_params]
        
        removed = []
        for key in keys_to_remove:
            if key in checkpoint['hyper_parameters']:
                del checkpoint['hyper_parameters'][key]
                removed.append(key)
        
        if removed:
            _LOGGER.info(f"\nRemoved conflicting parameters: {', '.join(removed)}")
        else:
            _LOGGER.info("\nNo conflicting parameters found to remove")
        
        _LOGGER.info("\nRemaining hyperparameters:")
        for key, value in checkpoint['hyper_parameters'].items():
            _LOGGER.info(f"  {key}: {value}")
        
        return checkpoint, removed == []

    def process_checkpoint(self, input_checkpoint, output_folder):
        """Main processing function with file/folder pickers"""
        
        if not input_checkpoint:
            _LOGGER.info("No checkpoint selected. Exiting.")
            return
        
        # Select output folder
        if not output_folder:
            _LOGGER.info("No output folder selected. Exiting.")
            return
        
        os.makedirs(output_folder, exist_ok=True)
        
        # Generate output filename
        input_filename = os.path.basename(input_checkpoint)
        output_filename = f"processed-{input_filename}"
        output_checkpoint = os.path.join(output_folder, output_filename)
        temp_checkpoint = os.path.join(output_folder, f"temp-{input_filename}")
        
        try:
            # Step 1: Load and convert checkpoint
            checkpoint = torch.load(input_checkpoint, weights_only=False, map_location='cpu')
            
            checkpoint = self.convert_paths(checkpoint)
            
            # Save temporary converted checkpoint
            
            torch.save(checkpoint, temp_checkpoint)
            
            checkpoint, is_changed = self.strip_checkpoint_params(checkpoint)
            
            if is_changed:
                torch.save(checkpoint, output_checkpoint)
            
            # Clean up temporary file
            if os.path.exists(temp_checkpoint):
                os.remove(temp_checkpoint)
                print("Temporary file cleaned up")
            
            return output_checkpoint
            
            
        except Exception as e:
            print(f"\n✗ Error: {e}")
            import traceback
            traceback.print_exc()
            
            # Clean up temporary file if it exists
            if os.path.exists(temp_checkpoint):
                os.remove(temp_checkpoint) 


def main():
    logging.basicConfig(level=logging.INFO)
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.deterministic = False
    _cli = VitsLightningCLI(  # noqa: ignore=F841
        VitsModel, VitsDataModule, trainer_defaults={"max_epochs": -1}
    )


# -----------------------------------------------------------------------------


if __name__ == "__main__":
    main()
