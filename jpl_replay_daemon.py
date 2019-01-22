import argparse
import sqlite3 as sql
import json
import smtplib
from datetime import datetime, timedelta
from time import sleep
import requests

# Split a string after a To: or From: to a User object
def parse_to_user(in_str):
    user_dict = {}
    # Are there any cases where there are multiple To recipients listed?
    split_str = in_str.split(" ")
    if len(from_split) > 1:
        user_dict["email_address"] = from_split[-1].replace("<", "").replace(">","")
        # If it looks like we have a first and last name, use them
        if len(from_split) = 3:
            user_dict["first_name"] = from_split[0]
            user_dict["last_name"] = from_split[1]
        # Otherwise put the non-address text into the first name field
        else:
            user_dict["first_name"] = " ".join(from_split[0:-1])
    else:
        user_dict["email_address"] = from_split[0].replace("<", "").replace(">","")
    return user_dict

def send_email(row, s):
    email_ids = row[0]
    filename  = row[2]
    # Load email json
    with open(filename, 'r') as f:
        email_json = json.load(f)
        print(email_json)
        content = email_json["body"][0]["content"]
        subject = content.split("Subject: ")[-1].split("\n")[0]
        from_str = content.split("From: ")[-1].split("\n")[0]
        to_str = content.split("To: ")[-1].split("\n")[0]
        content_type = email_json["body"][0]["content_type"]

    to_users = parse_to_user(to_str)
    from_user = parse_to_user(from_str)

    print("Subject: {}".format(subject))
    print("From: {}".format(from_str))
    print("To: {}".format(to_str))
    print("Content Type: {}".format(content_type))
    print("Content: {}".format(content)) 

    # Get chunkman email addresses that correspond to the JPL email addresses

    # Convert to and from addresses to API User objects

    # Stop here temporarily for testing
    return 0

    attachments = []

    # Parse the email content to build the email object
    email = {
         "sent_from": from_address,
         "sent_to": [],
         "sent_cc": [],
         "sent_bcc": [],
         "body": "",
         "subject": "",
         "attachments": attachments,
         "reply_to_id": "",
         "forward_id": "",
         "headers": []
         }
    
    # Send the email via the swagger API
    res = requests.post("https://box.chunkman.com:8080/requestSendMail", json=email)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    args = parser.parse_args()

    # Load credentials for JPL email address duplicates
    with open("/home/user/rosteen/seemail/server_code/jplcr.json") as f:
        creds = json.load(f)

    # Connect to database
    conn1 = sql.connect("/home/user-data/mail/jpl_emails.sqlite")
    cur1 = conn1.cursor()

    # Connect to the smtp server
    s = smtplib.SMTP("localhost:587")

    start_dt = datetime.now()
    while true:
        end_dt = start_dt + timedelta(seconds = 60)
        # Get the emails to send this minute and send them
        stmt = "select * from abuse where replay_timestamp > {} and replay_timestamp <= {}".format(start_dt, end_dt)
        cur1.execute(stmt)
        res = cur1.fetchall()

        # Send the emails
        for row in res:
            send_email(row)

        # Set the start time to the next minute and sleep for the rest of this minute
        # Should probably make sure email sends didn't take longer than expected 
        # and put us into the next time period
        start_dt = end_dt
        now = datetime.now()
        sleep_time = (end_dt - now).total_seconds()
        sleep(sleep_time)