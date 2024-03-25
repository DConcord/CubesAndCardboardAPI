# aws s3 cp ./boardgames_ranks.csv s3://dev-cubes-and-cardboard-backend/
import json
from thefuzz import fuzz
import csv

ALLOWED_ORIGINS = [
  'http://localhost:8080',
  'https://events.dev.dissonantconcord.com',
  'https://eventsdev.dissonantconcord.com',
  'https://events.cubesandcardboard.net',
  'https://www.cubesandcardboard.net',
  'https://cubesandcardboard.net'
]

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
  threshold = int(event['queryStringParameters']['threshold']) if 'threshold' in event['queryStringParameters'] else 90
  results = []
  bgg_ranks = csv.DictReader(open("boardgames_ranks.csv"))
  for row in bgg_ranks:
    match = fuzz.partial_ratio(game.lower(), row['name'].lower())
    if match > threshold:
      row['partial_ratio'] = match
      results.append(row)
  return {
    'statusCode': 200,
    'headers': {'Access-Control-Allow-Origin': origin},
    'body': json.dumps(results),
  } 
  # print(json.dumps(sorted(results, key=lambda k: k['partial_ratio']), indent=2))
    
# # def lambda_handler() 


# def getS3Object(bucket_name, file_path, decode='utf-8'):
#   s3 = boto3.resource('s3')
#   content_object = s3.Object(bucket_name, file_path)
#   file_content = content_object.get()['Body'].read().decode(decode)
#   return file_content

if __name__ == '__main__':
  
  
  search = "furnace"

  results = []
  bgg_ranks = csv.DictReader(open("boardgames_ranks.csv"))
  # bgg_ranks = csv.DictReader(getS3Object('dev-cubes-and-cardboard-backend', 'boardgames_ranks.csv'))
  # print(bgg_ranks.fieldnames)
  for row in bgg_ranks:
    match = fuzz.partial_ratio(search.lower(), row['name'].lower())
    if match > 90:
      row['partial_ratio'] = match
      results.append(row)
    # results
    # print(f"Similarity score: {fuzz.partial_ratio(search.lower(), row['name'].lower())}")
  print(json.dumps(sorted(results, key=lambda k: k['partial_ratio']), indent=2))
  # print(bgg_ranks)
  # full_name = "Star Wars: X-Wing (Second Edition)"

  