"""Produce the specification/image matrix without interpolating inputs into shell."""
import json
import os
from pathlib import Path
import re
import subprocess


def validate_tag(tag):
    if not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag):
        raise ValueError(f"Invalid Docker tag: {tag!r}")
    subprocess.run(["git", "check-ref-format", "--branch", tag], check=True, stdout=subprocess.DEVNULL)
    return tag


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch":
        inputs = event["inputs"]
        tag = validate_tag(inputs["docker_tag"])
        image = inputs["docker_image"].strip()
        if not image or image.startswith("-") or any(c.isspace() for c in image):
            raise ValueError("docker_image must be a full pullable image reference")
        targets = [{"tag": tag, "image": image}]
    else:
        repository = os.environ.get("DOCKER_IMAGE_REPOSITORY", "").strip()
        if not repository or repository.startswith("-") or any(c.isspace() for c in repository):
            raise ValueError("Set the DOCKER_IMAGE_REPOSITORY repository variable")
        tags = json.loads(os.environ.get("PUSH_DOCKER_TAGS", '["branch-main","latest"]'))
        if not isinstance(tags, list) or not tags:
            raise ValueError("PUSH_DOCKER_TAGS must be a nonempty JSON array of tags")
        tags = list(dict.fromkeys(validate_tag(tag) for tag in tags))
        targets = [{"tag": tag, "image": f"{repository}:{tag}"} for tag in tags]
    scripts = sorted(str(path) for path in Path("specifications").rglob("build.sh") if path.is_file())
    if not scripts:
        raise ValueError("No specifications/**/build.sh scripts found; no exports will be published")
    builds = [{**target, "script": script, "id": str(index)}
              for target in targets for index, script in enumerate(scripts)]
    if len(builds) > 256:
        raise ValueError("Build matrix exceeds GitHub's 256-job limit")
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write("builds=" + json.dumps({"include": builds}) + "\n")
        output.write("tags=" + json.dumps({"include": targets}) + "\n")


if __name__ == "__main__":
    main()
