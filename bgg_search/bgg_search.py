# aws s3 cp ./boardgames_ranks.csv s3://dev-cubes-and-cardboard-backend/
import json
import os
import csv
import boto3
import requests
import xmltodict
# from thefuzz import fuzz
from rapidfuzz import fuzz

ALLOWED_ORIGINS = [
  'http://localhost:8080',
  'https://events.dev.dissonantconcord.com',
  'https://eventsdev.dissonantconcord.com',
  'https://events.cubesandcardboard.net',
  'https://www.cubesandcardboard.net',
  'https://cubesandcardboard.net'
]

_ssm = boto3.client('ssm', region_name='us-east-1')
_bgg_api_token = _ssm.get_parameter(
    Name=os.environ['BGG_API_TOKEN_PARAM'],
    WithDecryption=True
)['Parameter']['Value']

def fetch_thumbnails(bgg_ids):
  ids_str = ','.join(str(i) for i in bgg_ids)
  response = requests.get(
      f'https://boardgamegeek.com/xmlapi2/thing?id={ids_str}',
      headers={'Authorization': f'Bearer {_bgg_api_token}'},
      timeout=10
  )
  data = xmltodict.parse(response.content)
  items = data.get('items', {}).get('item', [])
  if isinstance(items, dict):  # single result — xmltodict returns dict not list
    items = [items]
  return {item['@id']: item.get('thumbnail', '') for item in items}

def lambda_handler(event, context):
  origin = '*'
  if event and 'headers' in event and event['headers'] and 'Origin' in event['headers'] and event['headers']['Origin']:
    origin = event['headers']['Origin']

    if origin not in ALLOWED_ORIGINS:
      print(json.dumps(event))
      print(f"WARNING: origin '{origin}' not allowed")
      return {
        'statusCode': 401,
        'headers': {'Access-Control-Allow-Origin': 'https://events.cubesandcardboard.net'},
        'body': json.dumps({'message': 'CORS Failure'}),
      }
  unauthorized = {
    'statusCode': 401,
    'headers': {'Access-Control-Allow-Origin': origin},
    'body': json.dumps({'message': 'Not authorized'})
  }

  game = event['queryStringParameters']['game'] if 'game' in event['queryStringParameters'] else None
  threshold = int(event['queryStringParameters']['threshold']) if 'threshold' in event['queryStringParameters'] else 80
  results = []
  bgg_ranks = csv.DictReader(open("boardgames_ranks.csv"))
  for row in bgg_ranks:
    match = fuzz.token_sort_ratio(game.lower(), row['name'].lower())
    if match > threshold:
      row['partial_ratio'] = match
      results.append(row)

  top_results = results[:5]
  if top_results:
    try:
      thumbnails = fetch_thumbnails([r['id'] for r in top_results])
      for result in top_results:
        result['thumbnail'] = thumbnails.get(result['id'], '')
    except Exception as e:
      print(f"Failed to fetch thumbnails: {e}")
      for result in top_results:
        result['thumbnail'] = ''

  return {
    'statusCode': 200,
    'headers': {'Access-Control-Allow-Origin': origin},
    'body': json.dumps(top_results),
  }
  # print(json.dumps(sorted(results, key=lambda k: k['partial_ratio']), indent=2))

# # def lambda_handler()


# def getS3Object(bucket_name, file_path, decode='utf-8'):
#   s3 = boto3.resource('s3')
#   content_object = s3.Object(bucket_name, file_path)
#   file_content = content_object.get()['Body'].read().decode(decode)
#   return file_content

if __name__ == '__main__':


  search = "The Manhattan Project Energy Empre"

  results = []
  bgg_ranks = csv.DictReader(open("boardgames_ranks.csv"))
  # bgg_ranks = csv.DictReader(getS3Object('dev-cubes-and-cardboard-backend', 'boardgames_ranks.csv'))
  # print(bgg_ranks.fieldnames)
  for row in bgg_ranks:
    match = fuzz.token_sort_ratio(search.lower(), row['name'].lower())
    # match = fuzz.partial_ratio(search.lower(), row['name'].lower())
    if match > 75:
      row['partial_ratio'] = match
      results.append(row)
    # results
    # print(f"Similarity score: {fuzz.partial_ratio(search.lower(), row['name'].lower())}")
  print(json.dumps(results, indent=2))
  # print(json.dumps(sorted(results, key=lambda k: k['partial_ratio']), indent=2))

  # print(bgg_ranks)
  # full_name = "Star Wars: X-Wing (Second Edition)"


