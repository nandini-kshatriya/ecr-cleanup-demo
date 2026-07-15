import boto3
import subprocess
import sys

REGION = "ap-south-1"
REPO_NAME = "my-repo"
KEEP_COUNT = 10
S3_BUCKET = "ecr-backup-bucket-practice"
ARCHIVE_MODE = True

ecr = boto3.client("ecr", region_name=REGION)
sts = boto3.client("sts", region_name=REGION)


def get_registry_url():
    account_id = sts.get_caller_identity()["Account"]
    return f"{account_id}.dkr.ecr.{REGION}.amazonaws.com"


def get_sorted_images():
    paginator = ecr.get_paginator("describe_images")
    images = []
    for page in paginator.paginate(repositoryName=REPO_NAME):
        images.extend(page["imageDetails"])
    images.sort(key=lambda x: x["imagePushedAt"])
    return images


def get_primary_tag(image):
    tags = image.get("imageTags", [])
    for t in tags:
        if t != "latest":
            return t
    return tags[0] if tags else image["imageDigest"]


def archive_to_s3(image, registry_url):
    tag = get_primary_tag(image)
    image_uri = f"{registry_url}/{REPO_NAME}:{tag}"
    tarball = f"/tmp/{tag.replace('/', '_')}.tar"

    print(f"  Pulling {image_uri} ...")
    subprocess.run(["docker", "pull", image_uri], check=True)

    print(f"  Saving to {tarball} ...")
    subprocess.run(["docker", "save", "-o", tarball, image_uri], check=True)

    s3_key = f"{REPO_NAME}/{tag}/image.tar"
    print(f"  Uploading to s3://{S3_BUCKET}/{s3_key} ...")
    subprocess.run(
        ["aws", "s3", "cp", tarball, f"s3://{S3_BUCKET}/{s3_key}"],
        check=True,
    )
    print("  Archive complete.")


def delete_image(image):
    ecr.batch_delete_image(
        repositoryName=REPO_NAME,
        imageIds=[{"imageDigest": image["imageDigest"]}],
    )
    print(f"  Deleted digest {image['imageDigest']}")


def main():
    images = get_sorted_images()
    print(f"Total images in {REPO_NAME}: {len(images)}")

    if len(images) <= KEEP_COUNT:
        print(f"Nothing to do. {len(images)} <= {KEEP_COUNT}.")
        return

    excess = images[: len(images) - KEEP_COUNT]
    registry_url = get_registry_url()

    print(f"{len(excess)} image(s) exceed the limit of {KEEP_COUNT}. Processing oldest first...")

    for image in excess:
        tag = get_primary_tag(image)
        print(f"\nProcessing image tag={tag} pushed_at={image['imagePushedAt']}")
        try:
            if ARCHIVE_MODE:
                archive_to_s3(image, registry_url)
            delete_image(image)
        except subprocess.CalledProcessError as e:
            print(f"  ERROR processing {tag}: {e}", file=sys.stderr)
            continue


if __name__ == "__main__":
    main()
