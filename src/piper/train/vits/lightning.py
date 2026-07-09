"""PyTorch Lightning module."""

import ast
import logging
import operator
from functools import reduce
from typing import Optional

import lightning as L
import torch
from torch import autocast
from torch.nn import functional as F

from .commons import slice_segments
from .dataset import Batch
from .losses import discriminator_loss, feature_loss, generator_loss, kl_loss
from .mel_processing import mel_spectrogram_torch, spec_to_mel_torch
from .models import (
    MultiPeriodDiscriminator,
    MultiResolutionDiscriminator,
    SynthesizerTrn,
)
from .mos import MosPredictor

_LOGGER = logging.getLogger(__name__)


class VitsModel(L.LightningModule):
    def __init__(
        self,
        batch_size: int = 32,
        sample_rate: int = 22050,
        num_symbols: int = 256,
        num_speakers: int = 1,
        # audio
        resblock="2",
        resblock_kernel_sizes=(3, 5, 7),
        resblock_dilation_sizes=(
            (1, 2),
            (2, 6),
            (3, 12),
        ),
        upsample_rates=(8, 8, 4),
        upsample_initial_channel=256,
        upsample_kernel_sizes=(16, 16, 8),
        # mel
        filter_length: int = 1024,
        hop_length: int = 256,
        win_length: int = 1024,
        mel_channels: int = 80,
        mel_fmin: float = 0.0,
        mel_fmax: Optional[float] = None,
        # model
        inter_channels: int = 192,
        hidden_channels: int = 192,
        filter_channels: int = 768,
        n_heads: int = 2,
        n_layers: int = 6,
        kernel_size: int = 3,
        p_dropout: float = 0.1,
        n_layers_q: int = 3,
        use_spectral_norm: bool = False,
        gin_channels: int = 0,
        use_sdp: bool = True,
        segment_size: int = 8192,
        # Multi-Resolution STFT Discriminator (UnivNet/Vocos-style). Training-
        # only: sharpens spectral detail the period discriminators miss, at
        # ZERO inference cost (discriminators are discarded after training).
        # Opt-in so it never destabilizes the existing baseline.
        use_mrd: bool = False,
        # training
        learning_rate: float = 2e-4,
        learning_rate_d: float = 1e-4,
        betas: tuple[float, float] = (0.8, 0.99),
        betas_d: tuple[float, float] = (0.5, 0.9),
        eps: float = 1e-9,
        lr_decay: float = 0.999875,
        lr_decay_d: float = 0.9999,
        init_lr_ratio: float = 1.0,
        warmup_epochs: int = 0,
        c_mel: int = 45,
        c_kl: float = 1.0,
        grad_clip: Optional[float] = None,
        vocoder_warmstart_ckpt: Optional[str] = None,
        # Full non-strict warmstart: copy every matching-shape parameter from an
        # existing Piper checkpoint (generator + MPD), leaving any new modules
        # (e.g. the MRD) freshly initialized. Use this instead of --ckpt_path
        # when fine-tuning with use_mrd=true, since --ckpt_path does a strict
        # load that fails on the extra MRD keys. Starts a fresh optimizer.
        warmstart_ckpt: Optional[str] = None,
        # Optional no-reference MOS predictor for validation audio. Set to None
        # (or "none") to disable. Logged as "val_mos" -- a perceptual-quality
        # signal that can be monitored for early stopping (mode="max").
        mos_metric: Optional[str] = "utmos",
        # unused
        dataset: object = None,
        **kwargs,
    ):
        super().__init__()
        self.save_hyperparameters()

        if isinstance(self.hparams.resblock_kernel_sizes, str):
            self.hparams.resblock_kernel_sizes = ast.literal_eval(
                self.hparams.resblock_kernel_sizes
            )

        if isinstance(self.hparams.resblock_dilation_sizes, str):
            self.hparams.resblock_dilation_sizes = ast.literal_eval(
                self.hparams.resblock_dilation_sizes
            )

        if isinstance(self.hparams.upsample_rates, str):
            self.hparams.upsample_rates = ast.literal_eval(self.hparams.upsample_rates)

        if isinstance(self.hparams.upsample_kernel_sizes, str):
            self.hparams.upsample_kernel_sizes = ast.literal_eval(
                self.hparams.upsample_kernel_sizes
            )

        if isinstance(self.hparams.betas, str):
            self.hparams.betas = ast.literal_eval(self.hparams.betas)

        expected_hop_length = reduce(operator.mul, self.hparams.upsample_rates, 1)
        if expected_hop_length != hop_length:
            raise ValueError("Upsample rates do not match hop length")

        # Need to use manual optimization because we have multiple optimizers
        self.automatic_optimization = False

        self.batch_size = batch_size

        if (self.hparams.num_speakers > 1) and (self.hparams.gin_channels <= 0):
            # Default gin_channels for multi-speaker model
            self.hparams.gin_channels = 512

        # Used to partially load the state dict from a checkpoint.
        # Only the text/phoneme agnostic portions are loaded.
        self._vocoder_warmstart_ckpt = vocoder_warmstart_ckpt
        self._warmstart_ckpt = warmstart_ckpt

        # Set up models
        self.model_g = SynthesizerTrn(
            n_vocab=num_symbols,
            spec_channels=self.hparams.filter_length // 2 + 1,
            segment_size=self.hparams.segment_size // self.hparams.hop_length,
            inter_channels=self.hparams.inter_channels,
            hidden_channels=self.hparams.hidden_channels,
            filter_channels=self.hparams.filter_channels,
            n_heads=self.hparams.n_heads,
            n_layers=self.hparams.n_layers,
            kernel_size=self.hparams.kernel_size,
            p_dropout=self.hparams.p_dropout,
            resblock=self.hparams.resblock,
            resblock_kernel_sizes=self.hparams.resblock_kernel_sizes,
            resblock_dilation_sizes=self.hparams.resblock_dilation_sizes,
            upsample_rates=self.hparams.upsample_rates,
            upsample_initial_channel=self.hparams.upsample_initial_channel,
            upsample_kernel_sizes=self.hparams.upsample_kernel_sizes,
            n_speakers=self.hparams.num_speakers,
            gin_channels=self.hparams.gin_channels,
            use_sdp=self.hparams.use_sdp,
        )
        self.model_d = MultiPeriodDiscriminator(
            use_spectral_norm=self.hparams.use_spectral_norm
        )

        # Optional multi-resolution STFT discriminator (training-only).
        self.model_mrd: Optional[MultiResolutionDiscriminator] = None
        if self.hparams.use_mrd:
            self.model_mrd = MultiResolutionDiscriminator(
                use_spectral_norm=self.hparams.use_spectral_norm
            )

        # Optional perceptual-quality predictor (lazily loaded on first use).
        self._mos_predictor: Optional[MosPredictor] = None
        if mos_metric and (mos_metric.lower() != "none"):
            self._mos_predictor = MosPredictor(mos_metric.lower())

    def forward(self, text, text_lengths, scales, sid=None):
        noise_scale = scales[0]
        length_scale = scales[1]
        noise_scale_w = scales[2]
        audio, *_ = self.model_g.infer(
            text,
            text_lengths,
            noise_scale=noise_scale,
            length_scale=length_scale,
            noise_scale_w=noise_scale_w,
            sid=sid,
        )

        return audio

    def _compute_loss(self, batch: Batch):
        # g step
        x, x_lengths, y, _, spec, spec_lengths, speaker_ids = (
            batch.phoneme_ids,
            batch.phoneme_lengths,
            batch.audios,
            batch.audio_lengths,
            batch.spectrograms,
            batch.spectrogram_lengths,
            batch.speaker_ids if batch.speaker_ids is not None else None,
        )
        (
            y_hat,
            l_length,
            _attn,
            ids_slice,
            _x_mask,
            z_mask,
            (_z, z_p, m_p, logs_p, _m_q, logs_q),
        ) = self.model_g(x, x_lengths, spec, spec_lengths, speaker_ids)

        # Mel/STFT must run in fp32: cuFFT does not support bf16, and a stable
        # mel L1 wants full precision anyway. Disable autocast and cast the
        # (possibly bf16) generator audio to float here; the discriminators
        # below still see the autocast dtype for speed.
        with autocast(self.device.type, enabled=False):
            mel = spec_to_mel_torch(
                spec.float(),
                self.hparams.filter_length,
                self.hparams.mel_channels,
                self.hparams.sample_rate,
                self.hparams.mel_fmin,
                self.hparams.mel_fmax,
            )
            y_mel = slice_segments(
                mel,
                ids_slice,
                self.hparams.segment_size // self.hparams.hop_length,
            )
            y_hat_mel = mel_spectrogram_torch(
                y_hat.squeeze(1).float(),
                self.hparams.filter_length,
                self.hparams.mel_channels,
                self.hparams.sample_rate,
                self.hparams.hop_length,
                self.hparams.win_length,
                self.hparams.mel_fmin,
                self.hparams.mel_fmax,
            )
        y = slice_segments(
            y,
            ids_slice * self.hparams.hop_length,
            self.hparams.segment_size,
        )  # slice

        # Trim to avoid padding issues
        y_hat = y_hat[..., : y.shape[-1]]

        _y_d_hat_r, y_d_hat_g, fmap_r, fmap_g = self.model_d(y, y_hat)
        if self.model_mrd is not None:
            _y_dr_r, y_dr_g, fmap_r_mrd, fmap_g_mrd = self.model_mrd(y, y_hat)

        with autocast(self.device.type, enabled=False):
            # Generator loss
            mel_l1 = F.l1_loss(y_mel, y_hat_mel)
            kl = kl_loss(z_p, logs_q, m_p, logs_p, z_mask)

            loss_dur = torch.sum(l_length.float())
            loss_mel = mel_l1 * self.hparams.c_mel
            loss_kl = kl * self.hparams.c_kl

            loss_fm = feature_loss(fmap_r, fmap_g)
            loss_gen, _losses_gen = generator_loss(y_d_hat_g)
            loss_gen_all = loss_gen + loss_fm + loss_mel + loss_dur + loss_kl

            # Multi-resolution STFT discriminator (adversarial + feature match)
            loss_mrd_gen = y.new_zeros(())
            loss_mrd_fm = y.new_zeros(())
            if self.model_mrd is not None:
                loss_mrd_fm = feature_loss(fmap_r_mrd, fmap_g_mrd)
                loss_mrd_gen, _ = generator_loss(y_dr_g)
                loss_gen_all = loss_gen_all + loss_mrd_gen + loss_mrd_fm

        # d step
        y_d_hat_r, y_d_hat_g, _, _ = self.model_d(y, y_hat.detach())
        if self.model_mrd is not None:
            y_dr_r_det, y_dr_g_det, _, _ = self.model_mrd(y, y_hat.detach())

        with autocast(self.device.type, enabled=False):
            # Discriminator
            loss_disc, _losses_disc_r, _losses_disc_g = discriminator_loss(
                y_d_hat_r, y_d_hat_g
            )
            loss_disc_all = loss_disc

            loss_mrd_disc = y.new_zeros(())
            if self.model_mrd is not None:
                loss_mrd_disc, _, _ = discriminator_loss(y_dr_r_det, y_dr_g_det)
                loss_disc_all = loss_disc_all + loss_mrd_disc

        # Individual components for logging/monitoring. "mel" is the raw
        # (unweighted) mel L1, which is the most quality-correlated signal and
        # the recommended target for early stopping/checkpointing -- unlike the
        # adversarial losses, which only reflect the G/D equilibrium.
        metrics = {
            "mel": mel_l1.detach(),
            "kl": kl.detach(),
            "dur": loss_dur.detach(),
            "fm": loss_fm.detach(),
            "gen": loss_gen.detach(),
            "disc": loss_disc.detach(),
        }
        if self.model_mrd is not None:
            metrics["mrd_gen"] = loss_mrd_gen.detach()
            metrics["mrd_fm"] = loss_mrd_fm.detach()
            metrics["mrd_disc"] = loss_mrd_disc.detach()

        return loss_gen_all, loss_disc_all, metrics

    def training_step(self, batch: Batch, batch_idx: int):
        opt_g, opt_d = self.optimizers()
        loss_g, loss_d, metrics = self._compute_loss(batch)

        self.log("loss_g", loss_g, batch_size=self.batch_size)
        self.log_dict(
            {f"train_{name}": value for name, value in metrics.items()},
            batch_size=self.batch_size,
        )
        opt_g.zero_grad()
        # No retain_graph: loss_d is built from an independent discriminator
        # forward on y_hat.detach(), so freeing the generator graph here is
        # safe and cuts peak memory (lets larger batches fit on 24 GB).
        self.manual_backward(loss_g)
        opt_g.step()

        self.log("loss_d", loss_d, batch_size=self.batch_size)
        opt_d.zero_grad()
        self.manual_backward(loss_d)
        opt_d.step()

    def validation_step(self, batch: Batch, batch_idx: int):
        loss_g, _loss_d, metrics = self._compute_loss(batch)
        val_loss = loss_g  # kept for backwards compatibility
        self.log("val_loss", val_loss, batch_size=self.batch_size)

        # Lightning averages these across the validation epoch, giving a stable
        # per-epoch signal. "val_mel" (raw mel L1) is the recommended target for
        # EarlyStopping/ModelCheckpoint -- see train/__main__.py.
        self.log_dict(
            {f"val_{name}": value for name, value in metrics.items()},
            batch_size=self.batch_size,
            sync_dist=True,
        )
        return val_loss

    def on_validation_epoch_end(self) -> None:
        # Generate audio examples after validation, but not during sanity check.
        # Done in on_validation_epoch_end (not on_validation_end) so that
        # "val_mos" is logged before the EarlyStopping/ModelCheckpoint callbacks
        # read it.
        if self.trainer.sanity_checking:
            return

        has_audio_logger = bool(
            getattr(self, "logger", None)
            and hasattr(self.logger, "experiment")
            and hasattr(self.logger.experiment, "add_audio")
        )
        mos_enabled = self._mos_predictor is not None

        if not (has_audio_logger or mos_enabled):
            return

        mos_scores = []
        for utt_idx, test_utt in enumerate(self.trainer.datamodule.test_dataset):
            text = test_utt.phoneme_ids.unsqueeze(0).to(self.device)
            text_lengths = torch.LongTensor([len(test_utt.phoneme_ids)]).to(self.device)
            scales = [0.667, 1.0, 0.8]
            sid = (
                test_utt.speaker_id.to(self.device)
                if test_utt.speaker_id is not None
                else None
            )
            with torch.inference_mode():
                test_audio = self(text, text_lengths, scales, sid=sid).detach()

            # Score perceptual quality on the raw (un-normalized) audio.
            if mos_enabled:
                score = self._mos_predictor.score(test_audio, self.hparams.sample_rate)
                if score is not None:
                    mos_scores.append(score)

            if has_audio_logger:
                # Requires tensorboard. Scale to make louder in [-1, 1].
                norm_audio = test_audio * (1.0 / max(0.01, abs(test_audio).max()))
                tag = test_utt.text or str(utt_idx)
                # Pass global_step so each validation epoch's clip lands on its
                # own step. Without it, every epoch's audio is written at step 0,
                # and TensorBoard's audio dashboard can't scrub across epochs --
                # it mis-renders the stacked step-0 entries (clips show as 0s).
                self.logger.experiment.add_audio(
                    tag,
                    norm_audio,
                    sample_rate=self.hparams.sample_rate,
                    global_step=self.global_step,
                )

        if mos_scores:
            val_mos = sum(mos_scores) / len(mos_scores)
            self.log("val_mos", val_mos, prog_bar=True, sync_dist=True)

    def configure_optimizers(self):
        # The discriminator optimizer also drives the MRD when enabled, so its
        # parameters are updated by the same opt_d.step() in training_step.
        disc_params = list(self.model_d.parameters())
        if self.model_mrd is not None:
            disc_params += list(self.model_mrd.parameters())

        optimizers = [
            torch.optim.AdamW(
                self.model_g.parameters(),
                lr=self.hparams.learning_rate,
                betas=self.hparams.betas,
                eps=self.hparams.eps,
            ),
            torch.optim.AdamW(
                disc_params,
                lr=self.hparams.learning_rate_d,
                betas=self.hparams.betas_d,
                eps=self.hparams.eps,
            ),
        ]
        schedulers = [
            torch.optim.lr_scheduler.ExponentialLR(
                optimizers[0], gamma=self.hparams.lr_decay
            ),
            torch.optim.lr_scheduler.ExponentialLR(
                optimizers[1], gamma=self.hparams.lr_decay_d
            ),
        ]

        return optimizers, schedulers

    def _warmstart_vocoder_from_ckpt(self, ckpt_path: str):
        ckpt = torch.load(ckpt_path, map_location=self.device, weights_only=False)

        old_sd = ckpt["state_dict"]
        new_sd = self.state_dict()

        # Only keep vocoder/acoustic parts
        KEEP_PREFIXES = (
            "model_g.dec.",
            "model_g.enc_q.",
            "model_g.flow.",
        )

        copied = 0
        for k, v in old_sd.items():
            if not k.startswith(KEEP_PREFIXES):
                continue
            if (k in new_sd) and (new_sd[k].shape == v.shape):
                new_sd[k] = v
                copied += 1

        self.load_state_dict(new_sd, strict=False)
        _LOGGER.info(f"[warmstart] Copied {copied} vocoder parameters from {ckpt_path}")

    def _warmstart_from_ckpt(self, ckpt_path: str):
        """Copy all matching-shape params from a checkpoint (non-strict)."""
        ckpt = torch.load(ckpt_path, map_location=self.device, weights_only=False)
        old_sd = ckpt["state_dict"]
        new_sd = self.state_dict()

        copied, skipped = 0, 0
        for k, v in old_sd.items():
            if (k in new_sd) and (new_sd[k].shape == v.shape):
                new_sd[k] = v
                copied += 1
            else:
                skipped += 1

        self.load_state_dict(new_sd, strict=False)
        _LOGGER.info(
            "[warmstart] Copied %s parameters from %s (%s skipped; new modules "
            "such as the MRD start fresh)",
            copied,
            ckpt_path,
            skipped,
        )

    def on_fit_start(self):
        # Called once at the start of fit()
        if self._vocoder_warmstart_ckpt is not None:
            # Make sure we're on the correct device
            self._warmstart_vocoder_from_ckpt(self._vocoder_warmstart_ckpt)
            self._vocoder_warmstart_ckpt = None  # avoid re-running on restart

        if self._warmstart_ckpt is not None:
            self._warmstart_from_ckpt(self._warmstart_ckpt)
            self._warmstart_ckpt = None
