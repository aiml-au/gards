import logging

from glob import glob

from lavis.models import load_model_and_preprocess
from PIL import Image

import fire

logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def main(images="data/tiles/*.jpg", prefix="an aerial image of "):
    device = "cuda"

    model, vis_processors, text_processors = load_model_and_preprocess(
        "blip2_t5", "pretrain_flant5xxl", device=device, is_eval=True
    )

    for image_path in glob(images):
        im = Image.open(image_path)
        img_features = vis_processors["eval"](im).unsqueeze(0).to(device)

        model_output = model.generate(
            {"image": img_features, "prompt": prefix},
            use_nucleus_sampling=True,
            temperature=1,
            length_penalty=1,
            repetition_penalty=1.5,
            max_length=30,
        )

        caption = prefix + model_output[0]

        log.info(
            "Image {image_path} = {caption}".format(
                image_path=image_path, caption=caption
            )
        )


if __name__ == "__main__":
    fire.Fire(main)
