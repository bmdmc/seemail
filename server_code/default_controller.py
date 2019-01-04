import connexion
import six
import redis

from swagger_server.models.email import Email  # noqa: E501
from swagger_server.models.error import Error  # noqa: E501
from swagger_server.models.user import User  # noqa: E501
from swagger_server import util

import imbox
import random
import string
import json
import os
from glob import glob
from datetime import datetime
import logging

from kafka import KafkaProducer

import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# mailinabox management functions
import sys
sys.path.append('/root/mailinabox/management/')
import utils
import mailconfig

def generate_password(length = 18):
    return ''.join([random.choice(string.ascii_letters + string.digits ) for n in range(length)])

def create_bot_account_post(user):  # noqa: E501
    """Create a bot email account to send/receive messages from.

     # noqa: E501

    :param user: The bot user to send/receive messages from.
    :type user: dict | bytes

    :rtype: bool
    """
    bots_r = redis.StrictRedis(host='localhost', port=6379, db=2)
    deactivated_bots_r = redis.StrictRedis(host='localhost', port=6379, db=3)
    reactivating = False
    if connexion.request.is_json:
        user = User.from_dict(connexion.request.get_json())  # noqa: E501

    # Load mailinabox env variables
    env = utils.load_environment()

    # If we're reactivating a deactivated bot account, delete it from the deactivated list
    if user.email_address.encode('utf-8') in deactivated_bots_r.scan_iter():
        deactivated_bots_r.delete(user.email_address)
        reactivating = True

    # Load bot credentials file
    with open('/home/rosteen/seemail/server_code/bcr.json', 'r') as f:
        creds = json.load(f)

    # Generate a password and create the actual email account
    if user.email_address in creds:
        pwd = creds[user.email_address]
    else:
        pwd = generate_password()
        creds[user.email_address] = pwd
        with open('/home/rosteen/seemail/server_code/bcr.json', 'w') as f:
            json.dump(creds, f)

    # Add mailbox for bot
    res = mailconfig.add_mail_user(user.email_address, pwd, "", env)

    # Add to our Redis bot account db
    res = bots_r.set(user.email_address, 1)

    if reactivating is False:
        logging.info("Added bot account {}".format(user.email_address))
    else:
        logging.info("Reactivated bot account {}".format(user.email_address))    

    return res


def get_all_users():  # noqa: E501
    """Get all users on email server

     # noqa: E501


    :rtype: List[User]
    """
    bots_r = redis.StrictRedis(host='localhost', port=6379, db=2)
    deactivated_bots_r = redis.StrictRedis(host='localhost', port=6379, db=3)
    ## Not sure if this will work on all email implementations. 
    ## Needs location of mailboxes on server, and permission to access that location
    users = []
    domains = os.listdir('/home/user-data/mail/mailboxes')
    for domain in domains:
        temp_users = os.listdir('/home/user-data/mail/mailboxes/{}/'.format(domain))
        for name in temp_users:
            users.append("{}@{}".format(name, domain).encode('utf-8'))
    # Get bots to exclude, we only want to return real users
    bots = []
    for key in bots_r.scan_iter():
        bots.append(key)
    # also exclude deactivated bots
    for key in deactivated_bots_r.scan_iter():
        bots.append(key)
    users = list(set(users) - set(bots))
    # Decode from bytes to string for JSON encoding
    decoded_users = [User(email_address = x.decode('utf-8')) for x in users]
    logging.info("Returned list of users")
    return decoded_users


def monitor_users_get(email_addresses):  # noqa: E501
    """Add users to set to monitor email for (sent to kafka)

     # noqa: E501

    :param email_addresses: The full email addresses of the users to montor
    :type email_addresses: List[str]

    :rtype: List[bool]
    """
    users_r = redis.StrictRedis(host='localhost', port=6379, db=1)
    results = []
    for address in email_addresses:
        res = users_r.set(address, 1)
        results.append(res)
    
    logging.info("Added list of email addresses to monitor: {}".format(email_addresses))

    return results


def remove_bot_account_get(email_addresses):  # noqa: E501
    """Remove a bot email account to send/receive messages from.

     # noqa: E501

    :param email_addresses: The full email addresses of the bot user to remove
    :type email_addresses: str

    :rtype: bool
    """
    bots_r = redis.StrictRedis(host='localhost', port=6379, db=2)
    deactivated_bots_r = redis.StrictRedis(host='localhost', port=6379, db=3)
    # Delete account from Redis bot account db and add to defunct bots db
    for address in email_addresses:
        res = bots_r.delete(address)
        res2 = deactivated_bots_r.set(address, 1)
    logging.info("Deactivated list of bot accounts: {}".format(email_addresses))
    return res


def request_mail_history_get(email_addresses, request_key, back_to_iso_date_string):  # noqa: E501
    """Have all email involving users sent to historic kafka topic.

     # noqa: E501

    :param email_addresses: The full email addresses of the users to montor
    :type email_addresses: List[str]
    :param request_key: The provided key from requesting client to tag results with.
    :type request_key: str
    :param back_to_iso_date_string: The date back to retrieve email messages from.
    :type back_to_iso_date_string: str

    :rtype: List[bool]
    """
    res = []
    # Should add a check that the date is in the correct format, if there isn't one higher in the API definition
    in_dt = back_to_iso_date_string.split("T")[0].replace('-', '')
    back_to_unix = int((datetime.strptime(in_dt, '%Y%m%d')-datetime(1970,1,1)).total_seconds())

    producer = KafkaProducer(bootstrap_servers='localhost:9092',value_serializer=lambda v: json.dumps(v).encode('utf-8'))
    
    for address in email_addresses:
        try:
            user = address.split('@')[0]
            domain = address.split('@')[1]
            filelist = glob('/home/user-data/mail/mailboxes/{}/{}/*/*'.format(domain, user))
            for filename in filelist:
                # Skip if email timestamp before limit
                ts = int(filename.split('/')[-1].split('.')[0])
                if ts < back_to_unix:
                    continue
                mail = "".join(open(filename).readlines())
                mail_dict = imbox.parser.parse_email(mail)
                mail_dict['request_key'] = request_key # Add identifier to email
                # Need to decide whether to put transform function in this file or other
                transformed = transform_email(mail_dict)
                producer.send("history", transformed)
                producer.flush()
                res.append(True)
            logging.info("Sent email history for {}".format(address))
        except Exception as e:
            res.append(False)
            logging.error("Unable to send email history for {}:\n    {}".format(address, e))
    return res


def request_send_mail_post(email):  # noqa: E501
    """Send the email.

     # noqa: E501

    :param email: The email to send.
    :type email: dict | bytes

    :rtype: bool
    """
    if connexion.request.is_json:
        email = Email.from_dict(connexion.request.get_json())  # noqa: E501

    s = smtplib.SMTP("localhost:smtp")
    # Build MIME email from email object? Need to double check input format
    msg = MIMEMultipart()
    recipients = []
    for field in ('sent_to', 'sent_cc', 'sent_bcc'):
    	recipients += [x.email_address for x in email.field]
    msg['To'] = [x.email_address for x in email.sent_to]
    msg['CC'] = [x.email_address for x in email.sent_cc]
    msg['From'] = "{} {} <{}>".format(email.sent_from.first_name, 
        email.sent_from.last_name, email.sent_from.email_address)
    if email['reply_to_id'] != '':
        msg['In-Reply-To'] = email.reply_to_id
    msg['Subject'] = email.subject
    
    # Add additional headers
    for header in email.headers:
        if header.key not in msg:
            msg.add_header(header.key, header.value)

    msg.attach(MIMEText(email['body']))

    # Handle attachements
    for a in email.attachments:
        with open(a.name, 'rb') as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(f))
        part['Content-Disposition'] = 'attachment; filename="%s"' % basename(f)
        msg.attach(part)

    s.sendmail(email.sent_from.email_address, recipients, msg.as_string())
    s.close()
    logging.info("Sent email from {} to {}".format(email.sent_to, email.sent_from))
    return True


def unmonitor_users_get(email_addresses):  # noqa: E501
    """Remove users from set to monitor email for (sent to kafka)

     # noqa: E501

    :param email_addresses: The full email addresses of the users to unmonitor
    :type email_addresses: List[str]

    :rtype: List[bool]
    """
    users_r = redis.StrictRedis(host='localhost', port=6379, db=1)
    res_codes = {1: "Success", 0: "Failed"}
    results = []
    for address in email_addresses:
        res = users_r.delete(address)
        results.append(res_codes[res])
    logging.info("Unmonitored list of users: {}".format(email_addresses))
    return results
