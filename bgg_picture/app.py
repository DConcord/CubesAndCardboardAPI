import boto3
from PIL import Image, ImageOps
import requests
import xmltodict
import shutil
import os
import botocore
import json

_ssm = boto3.client('ssm', region_name='us-east-1')
_bgg_api_token = _ssm.get_parameter(
    Name=os.environ['BGG_API_TOKEN_PARAM'],
    WithDecryption=True
)['Parameter']['Value']

def lambda_handler(event, context):
    s3 = boto3.client("s3", region_name="us-east-1")
    for record in event['Records']:
        if 'Sns' not in record: 
            print(json.dumps(event))
            continue

        print(json.dumps(record))

        bgg_id = record['Sns']['MessageAttributes']['bgg_id']['Value']
        bucket = record['Sns']['MessageAttributes']['s3_bucket']['Value']
        pic_url = record['Sns']['MessageAttributes'].get('pic_url', {}).get('Value')
        refresh_image = record['Sns']['MessageAttributes'].get('refresh_image', {}).get('Value') == 'true'

        if key_exists(s3, bucket, f'{bgg_id}.png'):
          print(f"{bgg_id}.png already exists")
          continue
        retrieve_bgg_image(bgg_id, pic_url)

        # Resize
        img = Image.open(f"/tmp/{bgg_id}_original.png")
        img_ratio = img.size[0]/img.size[1]
        if img_ratio < .95 or img_ratio > 1.05:
            img = resize_with_padding(img, (600, 600))
        else:
            img.thumbnail((600, 600))

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

        if refresh_image:
          cf = boto3.client('cloudfront')
          cf.create_invalidation(
            DistributionId=os.environ['CLOUDFRONT_DISTRIBUTION_ID'],
            InvalidationBatch={
              'Paths': {'Quantity': 1, 'Items': [f'/{bgg_id}.png']},
              'CallerReference': str(bgg_id)
            }
          )
          print(f"CloudFront invalidation created for /{bgg_id}.png")

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
            print(f"ERROR: Unexpected S3 error checking key '{key}': {e}")
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

def retrieve_bgg_image(bgg_id, pic_url=None):
    bgg_image_original = f"/tmp/{bgg_id}_original.png"
    bgg_image_resized = f"/tmp/{bgg_id}.png"

    if os.path.exists(bgg_image_resized):
        return

    if os.path.exists(bgg_image_original) == False:
        if pic_url:
            # Use the admin-supplied URL instead of calling the BGG API
            print(f"Using custom pic_url for bgg_id {bgg_id}: {pic_url}")
            image_url = pic_url
        else:
            # Retrieve game image URL from BGG API
            bgg_id_url = f"https://boardgamegeek.com/xmlapi2/thing?id={bgg_id}"
            response = requests.get(
                bgg_id_url,
                headers={'Authorization': f'Bearer {_bgg_api_token}'},
                timeout=10
            )
            data = xmltodict.parse(response.content)
            image_url = data["items"]["item"]["image"]

        response = requests.get(image_url, stream=True, timeout=10)
        with open(bgg_image_original, 'wb') as out_file:
            shutil.copyfileobj(response.raw, out_file)

        return bgg_image_original

    

if __name__ == "__main__":
    # Localhost testing
    # lambda_handler(event={
    #     "Records": [ {"body": "172#cdkstack-bucket83908e77-7tr0zgs93uwh"},]
    # }, context={})


    tbd_pics = [
        "Game_TBD_32.jpeg", "Game_TBD_34.jpeg", "Game_TBD_33.jpeg"
    #     "Game_TBD_28.jpeg", "Game_TBD_29.jpeg", "Game_TBD_30.jpeg", "Game_TBD_31.jpeg",
    #     "Game_TBD_25.jpeg", "Game_TBD_27.jpeg", "Game_TBD_26.jpeg",
    # "Game_TBD_17.jpeg", "Game_TBD_24.jpeg", "Game_TBD_23.jpeg", "Game_TBD_22.jpeg", "Game_TBD_21.jpeg", "Game_TBD_20.jpeg", "Game_TBD_19.jpeg", "Game_TBD_18.jpeg"
    ]
    for pic in tbd_pics:
            
        # Resize
        img = Image.open(f"./tmp/{pic}")
        img_ratio = img.size[0]/img.size[1]
        if img_ratio < .95 or img_ratio > 1.05:
            img = resize_with_padding(img, (600, 600))
        else:
            img.thumbnail((600, 600))

        print(img.size)
        print(img.format)
        # img.show()
        img.save(f"./new/{pic}")