import boto3
from PIL import Image, ImageOps
import requests
# import urllib
import xmltodict
# import json
import shutil
import os
import botocore
# import io


def key_exists(s3, bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        print(f"Key: '{key}' found!")
        return True
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            print(f"Key: '{key}' does not exist!")
            return False
        else:
            print("Something else went wrong")
            raise


def resize_with_padding(img, expected_size):
    img.thumbnail((expected_size[0], expected_size[1]))
    # print(img.size)
    delta_width = expected_size[0] - img.size[0]
    delta_height = expected_size[1] - img.size[1]
    pad_width = delta_width // 2
    pad_height = delta_height // 2
    padding = (pad_width, pad_height, delta_width - pad_width, delta_height - pad_height)
    return ImageOps.expand(img, padding)

def retrieve_bgg_image(bgg_id):
    bgg_image_original = f"/tmp/{bgg_id}_original.png"
    bgg_image_resized = f"/tmp/{bgg_id}.png"

    if os.path.exists(bgg_image_resized):
        return
    
    if os.path.exists(bgg_image_original) == False:
        # Retrieve game data
        bgg_id_url = f"https://api.geekdo.com/xmlapi2/thing?id={bgg_id}"
        response = requests.get(bgg_id_url)
        data = xmltodict.parse(response.content)

        # Retrieve game image
        bgg_image_url = data["items"]["item"]["image"]
        response = requests.get(bgg_image_url, stream=True)
        with open(bgg_image_original, 'wb') as out_file:
            shutil.copyfileobj(response.raw, out_file)
        
        return bgg_image_original

    
def lambda_handler(event, context):
    s3 = boto3.client("s3", region_name="us-east-1")
    for record in event['Records']:
        # Retrieve (and split) bgg_id and S3 Bucket
        body_parse = record["body"].split("#")
        bgg_id = body_parse[0]
        bucket = body_parse[1]

        if key_exists(s3, bucket, f'{bgg_id}.png'):
          print(f"{bgg_id}.png already exists")
          continue
        retrieve_bgg_image(bgg_id)

        # Resize
        img = Image.open(f"/tmp/{bgg_id}_original.png")
        img_ratio = img.size[0]/img.size[1]
        if img_ratio < .95 or img_ratio > 1.05:
            img = resize_with_padding(img, (400, 400))
        else:
            img.thumbnail((400, 400))

        print(img.size)
        print(img.format)
        # img.show()
        img.save(f"/tmp/{bgg_id}.png")

        # Save the image to an in-memory file
        # in_mem_file = io.BytesIO()
        # img.save(in_mem_file, format=img.format)
        # in_mem_file.seek(0)

        # Upload image to s3
        # s3.upload_fileobj(
        s3.upload_file(
          f"/tmp/{bgg_id}.png",
          # io.BytesIO(img),
          bucket,
          f"{bgg_id}.png",
        )

if __name__ == "__main__":
  # Localhost testing
  lambda_handler(event={
    "Records": [ {"body": "172#cdkstack-bucket83908e77-7tr0zgs93uwh"},]
   }, context={})
