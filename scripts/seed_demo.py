"""Generate public, deterministic examples in an explicitly empty directory."""

import argparse
import math
import os
from pathlib import Path


def seed(directory: Path):
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Demo destination must be empty")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.environ["TRACKIO_DIR"] = str(directory.resolve())
    os.environ["TRACKIO_STORAGE_MODE"] = "sqlite"
    for key in ("TRACKIO_SERVER_URL", "TRACKIO_SPACE_ID", "TRACKIO_BUCKET_ID"):
        os.environ.pop(key, None)
    import tempfile

    import trackio
    from PIL import Image, ImageDraw

    with tempfile.TemporaryDirectory() as tmp:
        image = Image.new("RGB", (480, 320), "#e8eefb")
        draw = ImageDraw.Draw(image)
        draw.rectangle((50, 60, 200, 260), fill="#365cc4")
        draw.ellipse((240, 70, 420, 250), fill="#5c9c80")
        image_path = Path(tmp) / "synthetic-shapes.png"
        image.save(image_path)
        file = Path(tmp) / "evaluation-config-with-a-representative-long-filename.json"
        file.write_text(
            '{"dataset": "synthetic", "seed": 42, "purpose": "public example"}\n'
        )
        for run_index in range(3):
            run = trackio.init(
                project="lens-demo",
                name=f"experiment-{run_index}-long-name-learning-rate-comparison",
                config={
                    "learning_rate": 0.001 * (run_index + 1),
                    "model": "synthetic-small",
                    "seed": 42 + run_index,
                    "description": "A reproducible example with long configuration text "
                    * 8,
                },
                auto_log_gpu=False,
                auto_log_cpu=False,
                capture_console=False,
            )
            for step in range(160):
                metrics = {
                    "train/loss": math.exp(-step / 45) + run_index * 0.03,
                    "eval/accuracy": 0.6 + 0.3 * step / 160,
                }
                if step % 11 == 0:
                    metrics.pop("eval/accuracy")
                metrics.update(
                    {
                        f"diagnostics/metric_{i:02d}": math.sin(step / 20 + i)
                        + run_index
                        for i in range(18)
                    }
                )
                run.log(metrics, step=step)
            for step in range(8):
                trackio.log_system(
                    {"cpu/usage_percent": 30 + step, "memory/used_gb": 2 + step / 10}
                )
            run.log(
                {
                    "samples": trackio.Image(str(image_path)),
                    "evaluation_report": trackio.Markdown(
                        "# Synthetic evaluation report\n\n"
                        + "\n\n".join(
                            f"## Section {n}\n\nMissing observations remain missing. **Comparison** uses the original measurements. `configuration_with_a_very_long_identifier_for_phone_layout_checks`\n\n- Loss decreases over time.\n- No real experiments are included."
                            for n in range(15)
                        )
                    ),
                },
                step=160,
            )
            trackio.save(str(file))
            run.log_artifact(
                file, name="evaluation-config", type="config", aliases=["latest"]
            )
            run.finish()
    from trackio.sqlite_storage import SQLiteStorage

    SQLiteStorage.init_db("empty-demo")


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    seed(parser.parse_args().directory)
