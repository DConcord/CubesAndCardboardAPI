import { APIGatewayProxyEvent, APIGatewayProxyResult } from "aws-lambda";
import { SQSClient, ReceiveMessageCommand, Message, DeleteMessageCommand } from "@aws-sdk/client-sqs";
import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";
import { SESv2Client, SendEmailCommand } from "@aws-sdk/client-sesv2";
import { GetItemCommand, GetItemInput, DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { marshall, unmarshall } from "@aws-sdk/util-dynamodb";
import { NodeJsClient } from "@smithy/types";
import inlineCss from "inline-css";

import * as yaml from "js-yaml";

type MODES = "prod" | "dev";

// Pull Environment Variables supplied by Lambda (or default dev values if running locally)
const MODE: MODES = process.env.MODE ? (process.env.MODE as MODES) : "dev";
const RSVP_SQS_URL = process.env.RSVP_SQS_URL ? process.env.RSVP_SQS_URL : "";
const S3_BUCKET = process.env.S3_BUCKET ? process.env.S3_BUCKET : "cdkstack-bucketdevff8a9acd-pine3ubqpres";
const TABLE_NAME = process.env.TABLE_NAME ? process.env.TABLE_NAME : "game_events_dev";
const BACKEND_BUCKET = process.env.BACKEND_BUCKET ? process.env.BACKEND_BUCKET : "dev-cubes-and-cardboard-backend";

/**
 *
 * Event doc: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-input-format
 * @param {Object} event - API Gateway Lambda Proxy Input Format
 *
 * Return doc: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html
 * @returns {Object} object - API Gateway Lambda Proxy Output Format
 *
 */

const config = {
  region: "us-east-1",
};

const rsvp_swap = {
  attending: "not_attending" as "not_attending",
  not_attending: "attending" as "attending",
};

const rsvp_transform = {
  attending: "attending" as "attending",
  not_attending: "not attending" as "not attending",
};

const sqs = new SQSClient(config);
const s3 = new S3Client(config) as NodeJsClient<S3Client>;
const ses = new SESv2Client(config);
const ddb = new DynamoDBClient(config);

// Retrieve GameKnightEvent from DynamoDB
async function getEvent(
  event_id: string,
  attributes: string[] = [],
  suppressLog = false
): Promise<ExistingGameKnightEventDDB | undefined> {
  const getItemInput: GetItemInput = {
    TableName: TABLE_NAME,
    Key: marshall({ event_id: event_id }),
  };

  if (attributes.length > 0) {
    getItemInput.ProjectionExpression = attributes.join(",");
  }

  const getItemCommand = new GetItemCommand(getItemInput);

  try {
    const { Item } = await ddb.send(getItemCommand);
    if (!Item) {
      if (!suppressLog) console.warn(`Event ${event_id} not found`);
      return undefined;
    }

    const event: ExistingGameKnightEventDDB = unmarshall(Item) as ExistingGameKnightEventDDB;

    if (event.not_attending.has("placeholder")) {
      event.not_attending.delete("placeholder");
    }
    if (event.attending.has("placeholder")) {
      event.attending.delete("placeholder");
    }
    if (event.player_pool.has("placeholder")) {
      event.player_pool.delete("placeholder");
    }
    // if (event.finalScore) {
    //   event.finalScore = JSON.parse(event.finalScore);
    // }

    return event;
  } catch (err) {
    console.error(err);
    throw err;
  }
}

// run myMain() when running the script directly from local dev cli
if (typeof require !== "undefined" && require.main === module) {
  myMain();
}

async function myMain() {
  // timestamp 1m ago
  const timestamp = new Date(new Date().getTime() - 60000).toLocaleString("en-US", {
    timeZone: "America/Denver",
    timeStyle: "short",
    dateStyle: "short",
  }); //timeZoneName: "short",

  const fs = require("fs");

  const htmlTemplate = fs.readFileSync("./template.html").toString();
  const body = fs.readFileSync("./testHTML/Body.html").toString();
  const footer = fs.readFileSync("./testHTML/Footer.html").toString();

  const rsvpFinalHtmlCss = htmlTemplate
    .replace("{{Title}}", `${MODE == "dev" ? "Dev " : ""}Game Knight Events RSVP notification`)
    .replace("{{Preheader}}", `${timestamp}`)
    .replace("{{Body}}", `<h3>${timestamp}</h3>${body}`)
    .replace("{{Footer}}", footer);

  inlineCss(rsvpFinalHtmlCss, { url: " " }).then(function (html) {
    console.log(html);
  });
  process.exit;

  // const getEventPromises = [
  //   getEvent("a81909cd-009a-47dc-ba6a-2d2f26cbefde"),
  //   getEvent("da3820fe-04ff-4949-8c13-63a6c21fa3f5"),
  // ];
  // console.log(`getEventPromises: ${getEventPromises.length}`);
  // const retrievedEvents = await Promise.allSettled(getEventPromises);
  // console.log(JSON.stringify({ retrievedEvents: retrievedEvents }, null, 2));
  process.exit;
}

interface SendEmailProps {
  fromAddress?: string;
  toAddresses: string[];
  subject?: string;
  textBody: string;
  htmlBody: string;
}

const SendEmail = async ({
  fromAddress = MODE === "dev"
    ? "Game Knight DEV RSVP Alert <alert@mail.cubesandcardboard.net>"
    : "Game Knight RSVP Alert <alert@mail.cubesandcardboard.net>",
  toAddresses,
  subject = MODE === "dev" ? "DEV RSVP Alert" : "RSVP Alert",
  textBody,
  htmlBody,
}: SendEmailProps) => {
  const SendEmailRequest = {
    FromEmailAddress: fromAddress,
    Destination: {
      ToAddresses: toAddresses,
    },
    Content: {
      Simple: {
        Subject: {
          Data: subject,
        },
        Body: {
          Text: {
            Data: textBody,
          },
          Html: {
            Data: htmlBody,
          },
        },
        // Headers: [
        //   // MessageHeaderList
        //   {
        //     // MessageHeader
        //     Name: " X-Entity-Ref-ID", // required
        //     Value: "RSVP_Alert", // required
        //   },
        // ],
      },
    },
  };
  const response = await ses.send(new SendEmailCommand(SendEmailRequest));
  return response;
};

async function GetS3Object(Key: string, Bucket: string) {
  const response = await s3.send(
    new GetObjectCommand({
      Bucket: Bucket, // S3_BUCKET,
      Key: Key,
    })
  );
  const body = await response.Body!.transformToString();
  // console.log(body)
  return body;
}

const DeleteMessage = (ReceiptHandle: string) =>
  new DeleteMessageCommand({
    QueueUrl: RSVP_SQS_URL,
    ReceiptHandle: ReceiptHandle,
  });

const ReceiveMessage = () =>
  new ReceiveMessageCommand({
    QueueUrl: RSVP_SQS_URL, // required
    MaxNumberOfMessages: 10,
    WaitTimeSeconds: 10,
  });

export const lambdaHandler = async (lambdaEvent: APIGatewayProxyEvent): Promise<APIGatewayProxyResult> => {
  try {
    // const messages: Message[] = [];
    const rsvpLogs: RsvpLogType[] = [];

    let start = true;
    let response;
    let i = 1; // Message sequence number
    while (start || (response!.Messages && response!.Messages.length == 10)) {
      console.log("Retrieving Messages");
      response = await sqs.send(ReceiveMessage());
      if (response.Messages) {
        console.log(`response.Messages count: ${response.Messages.length}`);
        // messages.push(...response.Messages);

        let awaitDeleteMessages = [];
        for (const message of response.Messages) {
          rsvpLogs.push({ num: i, ...JSON.parse(message.Body!) });
          i++;
          awaitDeleteMessages.push(sqs.send(DeleteMessage(message.ReceiptHandle!)));
        }
        await Promise.allSettled(awaitDeleteMessages);
      } else {
        if (start) return { statusCode: 200, body: JSON.stringify({ message: "No new RSVP Messages" }) };
        console.log("No more messages");
      }
      start = false;
    }
    console.log(`Total Messages: ${rsvpLogs.length}`);
    // console.log(messages);

    const RetrieveS3 = await Promise.allSettled([
      GetS3Object("events.json", S3_BUCKET),
      GetS3Object("players_groups.json", BACKEND_BUCKET),
      GetS3Object("email_alert_preferences.json", BACKEND_BUCKET),
      GetS3Object("template.html", BACKEND_BUCKET),
    ]);
    console.log("%j", { RetrieveS3: RetrieveS3 });
    const events: ExistingGameKnightEvent[] = RetrieveS3[0].status === "fulfilled" && JSON.parse(RetrieveS3[0].value);
    const players_groups: PlayersGroups = RetrieveS3[1].status === "fulfilled" && JSON.parse(RetrieveS3[1].value);
    const email_alert_preferences: AllEmailAlertPreferences =
      RetrieveS3[2].status === "fulfilled" && JSON.parse(RetrieveS3[2].value);
    const htmlTemplate = RetrieveS3[3].status === "fulfilled" ? RetrieveS3[3].value : "";

    const eventsDict: EventDict = Object.fromEntries(events.map((event) => [event.event_id, event]));
    const playersDict = players_groups.Users;

    // Pull events that aren't in the public s3 events.json (such as Private Events)
    const getEventPromises = [...new Set(rsvpLogs.map((log) => log.event_id))]
      .map((event_id) => !(event_id in eventsDict) && getEvent(event_id))
      .filter((x) => x); // !== null && x !== undefined);
    console.log(`getEventPromises: ${getEventPromises.length}`);
    if (getEventPromises.length > 0) {
      console.log("Retrieving Events");
      const retrievedEvents = await Promise.allSettled(getEventPromises);
      console.log("%j", { retrievedEvents: retrievedEvents });
      for (const result of retrievedEvents) {
        if (result.status === "fulfilled") {
          if (result.value) eventsDict[result.value.event_id] = result.value;
          else console.error(result);
        } else console.error("%j", result);
      }
    }

    // Sort RSVP Logs by Event Date (but preserves original order of operations otherwise)
    rsvpLogs.sort(function (a, b) {
      if (eventsDict[a.event_id].date < eventsDict[b.event_id].date) return -1;
      if (eventsDict[a.event_id].date > eventsDict[b.event_id].date) return 1;
      return 0;
    });

    const rsvpFinal: RsvpFinalType = {};
    const rsvpDebug: { [key: string]: string[] } = {};
    for (const log of rsvpLogs) {
      const timestamp = new Date(log.timestamp).toLocaleString("en-US", {
        timeZone: "America/Denver",
        timeStyle: "short",
        dateStyle: "short",
      });
      const event = eventsDict[log.event_id];
      if (!(log.event_id in rsvpFinal)) rsvpFinal[log.event_id] = {};
      if (!(log.user_id in rsvpFinal[log.event_id]))
        rsvpFinal[log.event_id][log.user_id] = { originalRsvp: "", finalRsvp: "", finalSentence: "" };

      const event_str = event ? `${event.game} (${formatIsoDate(event.date)})` : `Date: ${formatIsoDate(log.date)}`;
      if (!(event_str in rsvpDebug)) rsvpDebug[event_str] = [];
      const rsvp = log.rsvp.replace("_", " ");

      var subject: string;
      var verb: string;
      var object = "";
      var original: string;
      var result: string;
      var sentence = "";
      var selfUpdated = false;
      switch (log.auth_type) {
        // If player changed their own RSVP, they are the subject and the object is their own pronoun
        case "self":
          subject = playersDict[log.user_id].attrib.given_name;
          selfUpdated = true;
          break;

        // If admin or host changed a player's RSVP, the admin/host is the subject and the player is the object
        default:
          subject = `${playersDict[log.auth_sub].attrib.given_name} (${log.auth_type})`;
          object = playersDict[log.user_id].attrib.given_name;
          break;
      }

      let { originalRsvp, finalRsvp } = rsvpFinal[log.event_id][log.user_id];
      switch (log.action) {
        case "delete":
          if (!originalRsvp)
            rsvpFinal[log.event_id][log.user_id].originalRsvp = log.rsvp.replace("_", " ") as
              | "attending"
              | "not attending"
              | "undecided";
          verb = "changed";
          original = rsvp;
          result = "undecided";
          rsvpFinal[log.event_id][log.user_id].finalRsvp = "undecided";
          sentence = selfUpdated
            ? `${timestamp}: ${subject} ${verb} from ${original} to ${result}`
            : `${timestamp}: ${subject} ${verb} ${object} from ${original} to ${result}`;
          break;
        case "add":
          if (!originalRsvp) rsvpFinal[log.event_id][log.user_id].originalRsvp = "undecided";
          verb = "marked";
          result = rsvp;
          rsvpFinal[log.event_id][log.user_id].finalRsvp = rsvp_transform[log.rsvp];
          sentence = selfUpdated
            ? `${timestamp}: ${subject} replied as ${result}`
            : `${timestamp}: ${subject} marked ${object} as ${result}`;
          break;
        case "update":
          if (!originalRsvp) rsvpFinal[log.event_id][log.user_id].originalRsvp = rsvp_transform[rsvp_swap[log.rsvp]];
          verb = "changed";
          original = rsvp_swap[log.rsvp].replace("_", " ");
          result = rsvp;
          rsvpFinal[log.event_id][log.user_id].finalRsvp = rsvp_transform[log.rsvp];
          sentence = selfUpdated
            ? `${timestamp}: ${subject} ${verb} from ${original} to ${result}`
            : `${timestamp}: ${subject} ${verb} ${object} from ${original} to ${result}`;
          break;
      }
      rsvpDebug[event_str].push(sentence);

      ({ originalRsvp, finalRsvp } = rsvpFinal[log.event_id][log.user_id]);
      // prettier-ignore
      rsvpFinal[log.event_id][log.user_id].finalSentence = 
        originalRsvp == "undecided"
          ? selfUpdated
            ? `${subject} replied as ${finalRsvp}`
            : `${subject} marked ${object} as ${finalRsvp}`
        // all other originalRsvp:
          : selfUpdated
            ? `${subject} changed from ${originalRsvp} to ${finalRsvp}`
            : `${subject} changed ${object} from ${originalRsvp} to ${finalRsvp}`;
    }

    console.log("%j", { rsvpDebug: rsvpDebug, rsvpFinal: rsvpFinal });

    for (const [event_id, eventRsvps] of Object.entries(rsvpFinal)) {
      for (const [user_id, rsvp] of Object.entries(eventRsvps)) {
        let { originalRsvp, finalRsvp } = rsvp;
        if (originalRsvp == finalRsvp) delete rsvpFinal[event_id][user_id];
      }
      if (Object.keys(rsvpFinal[event_id]).length == 0) delete rsvpFinal[event_id];
    }

    const { rsvp_all_debug, rsvp_all, rsvp_hosted } = email_alert_preferences;

    if (Object.keys(rsvpFinal).length == 0 && rsvp_all_debug.length === 0) {
      console.log(`No new RSVPs. rsvpFinal: 0; rsvp_all_debug: 0`);
      return { statusCode: 200, body: JSON.stringify({ message: "No new RSVPs" }) };
    }

    // Process rsvp_all_debug subscriptions
    // All changes without reducing to just beginning and end result
    const rsvpDebug_html: string =
      rsvp_all_debug.length === 0
        ? ""
        : Object.entries(rsvpDebug)
            .map(([event, sentences]) => {
              let _string = `<div class="game">${event}</div>`;
              const _sentences = sentences.map((sentence) => `<div class="rsvp">${sentence}</div>`).join("");
              return _string + _sentences;
            })
            .join("") + "<br><br>";
    const allFormattedEventRsvpsDEBUG =
      rsvp_all_debug.length === 0
        ? { textBody: "", htmlBody: "" }
        : await formatEventRsvps(rsvpFinal, eventsDict, htmlTemplate, rsvpDebug_html);
    const rsvp_all_debug_promises = rsvp_all_debug.map(async (user_id) =>
      SendEmail({ toAddresses: [playersDict[user_id].attrib.email], ...allFormattedEventRsvpsDEBUG })
    );
    console.log(`rsvp_all_debug_promises count: ${rsvp_all_debug_promises.length}`);

    // Process rsvp_all subscriptions
    const allFormattedEventRsvps =
      rsvp_all.length === 0
        ? { textBody: "", htmlBody: "" }
        : await formatEventRsvps(rsvpFinal, eventsDict, htmlTemplate);
    console.log("primary formatting complete");
    const rsvp_all_promises = rsvp_all.map((user_id) =>
      SendEmail({ toAddresses: [playersDict[user_id].attrib.email], ...allFormattedEventRsvps })
    );
    console.log(`rsvp_all_promises count: ${rsvp_all_promises.length}`);

    const rsvp_hosted_promises = rsvp_hosted
      .map(async (user_id) => {
        const hostEvents = Object.keys(rsvpFinal).filter((event_id) => eventsDict[event_id].host == user_id);
        if (hostEvents.length > 0) {
          const hostEventRsvps = Object.fromEntries(hostEvents.map((event_id) => [event_id, rsvpFinal[event_id]]));
          return SendEmail({
            toAddresses: [playersDict[user_id].attrib.email],
            ...(await formatEventRsvps(hostEventRsvps, eventsDict, htmlTemplate)),
          });
        }
      })
      .filter((x) => x !== undefined);
    console.log(`rsvp_hosted_promises count: ${rsvp_hosted_promises.length}`);
    const sesAllSettled = await Promise.allSettled([
      ...rsvp_hosted_promises,
      ...rsvp_all_promises,
      ...rsvp_all_debug_promises,
    ]);
    console.log("%j", { sesAllSettled: sesAllSettled });

    return {
      statusCode: 200,
      body: "Success",
    };
  } catch (err) {
    console.error(err);
    return {
      statusCode: 500,
      body: JSON.stringify({
        message: "some error happened",
      }),
    };
  }
};

interface RsvpFinalType {
  [event_id: string]: {
    [user_id: string]: {
      originalRsvp: "attending" | "not attending" | "undecided" | "";
      finalRsvp: "attending" | "not attending" | "undecided" | "";
      finalSentence: string;
    };
  };
}
async function formatEventRsvps(
  rsvpFinal: RsvpFinalType,
  eventsDict: EventDict,
  htmlTemplate: string,
  extraHtmlBody: string = ""
) {
  // timestamp 1m ago
  const timestamp = new Date(new Date().getTime() - 60000).toLocaleString("en-US", {
    timeZone: "America/Denver",
    timeStyle: "short",
    dateStyle: "short",
  }); //timeZoneName: "short",

  const rsvpHtmlBody: string = Object.entries(rsvpFinal)
    .map(([event_id, eventRsvps]) => {
      const event = eventsDict[event_id];
      const event_str = `${event.game} (${formatIsoDate(event.date)})`;
      const _string = `<div class="game">${event_str}</div>`;
      const _sentences = Object.entries(eventRsvps)
        .map(([user_id, rsvp]) => {
          return `<div class="rsvp">${rsvp.finalSentence}</div>`.replaceAll(
            /((not )?attending|undecided)/gm,
            "<b>$1</b>"
          );
        })
        .join("\n");
      return _string + "\n" + _sentences;
    })
    .join("\n");

  const footer = `You can manage alert preferences under your profile at the top of the <a href="https://${
    websiteFQDN[MODE]
  }">${MODE === "dev" ? "Dev " : ""}Game Knight Events</a> website`;

  const rsvpFinalHtmlCss = htmlTemplate
    .replace("{{Title}}", `${MODE == "dev" ? "Dev " : ""}Game Knight Events RSVP notification`)
    .replace("{{Preheader}}", `${timestamp}`)
    .replace("{{Body}}", `<h3>${timestamp}</h3>${extraHtmlBody}${rsvpHtmlBody}`)
    .replace("{{Footer}}", footer);
  const rsvpFinalHtml = await inlineCss(rsvpFinalHtmlCss, { url: " ", removeStyleTags: true });

  const rsvpFinalParsed = Object.fromEntries(
    Object.entries(rsvpFinal).map(([event_id, eventRsvps]) => {
      const event = eventsDict[event_id];
      const event_str = `${event.game} (${formatIsoDate(event.date)})`;
      return [event_str, Object.values(eventRsvps).map((rsvp) => rsvp.finalSentence)];
    })
  );

  const rsvpFinalText =
    yaml
      .dump(rsvpFinalParsed, { indent: 2, lineWidth: -1, noCompatMode: true })
      .replaceAll(/''/gm, "'")
      .replaceAll(/(\'$|^\')/gm, "")
      .replaceAll(/':/g, ":")
      .replaceAll(/- '/g, "")
      .replaceAll(/((not )?attending|undecided)/gm, '"$1"') +
    "\n\n" +
    `You can manage alert preferences under your profile at the top of the ${
      MODE === "dev" ? "Dev " : ""
    }Events website (https://${websiteFQDN[MODE]})`;

  return { textBody: rsvpFinalText, htmlBody: rsvpFinalHtml };
}

function formatIsoDate(isoString: string) {
  return new Date(isoString).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "America/Denver",
  });
}

const websiteFQDN = {
  dev: "events.cubesandcardboard.net",
  prod: "eventsdev.dissonantconcord.com",
};

type LogType = {
  timestamp: string;
  log_type: "event" | "rsvp" | "player";
  date: string;
  action: "create" | "update" | "delete" | "modify" | "add";
  auth_sub: string;
  auth_type: "admin" | "self" | "host";
  previous: Object;
  new: Object;
  event_id: string;
  user_id: string;
  rsvp: "attending" | "not_attending";
  attrib: string;
};
type RsvpLogType = Omit<LogType, "previous" | "new" | "attrib">;
// type EventLogType = Omit<LogType, "event_id" | "user_id" | "rsvp" | "attrib">;
// type PlayerLogType = Omit<LogType, "date" | "previous" | "new" | "event_id" | "rsvp">;

type AllEmailAlertPreferences = {
  rsvp_all_debug: string[];
  rsvp_all: string[];
  rsvp_hosted: string[];
};

type PlayerEmailAlertPreferences = {
  [alert_type in keyof AllEmailAlertPreferences]: boolean;
};

export type PlayersGroups = {
  Users: PlayersDict;
  Groups: {
    [key: string]: string[];
  };
};

export type PlayersDict = {
  [key: string]: PlayerGet;
};

export type PlayerGet = {
  groups: string[];
  attrib: {
    given_name: string;
    family_name?: string;
    email: string;
    phone_number?: string;
  };
};

export interface EventDict {
  [key: ExistingGameKnightEvent["event_id"]]: ExistingGameKnightEvent | ExistingGameKnightEventDDB;
}

export interface ExistingGameKnightEvent extends GameKnightEvent {
  event_id: string;
}
export interface ExistingGameKnightEventDDB
  extends Omit<GameKnightEvent, "attending" | "not_attending" | "player_pool" | "organizer_pool"> {
  event_id: string;
  attending: Set<string>;
  not_attending: Set<string>;
  player_pool: Set<string>;
  organizer_pool: Set<string>;
}

export type GameKnightEvent = {
  event_id?: string;
  event_type: string;
  date: string;
  host: string;
  organizer: string;
  format: "Open" | "Reserved" | "Private";
  game: string;
  bgg_id?: number;
  total_spots?: number;
  registered?: string[];
  attending: string[];
  not_attending: string[];
  player_pool: string[];
  organizer_pool: string[];
  tbd_pic?: string;
  migrated?: boolean;
  status?: "Normal" | "Cancelled";
  // finalScore?: PlayerScore[];
};
