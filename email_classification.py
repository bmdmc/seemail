###############################################################################
# Run some simple classification models on the JPL Abuse dataset to get an
# initial look at what baseline performance is.
#
# Some code shamelessly based off of
# https://www.kdnuggets.com/2017/03/email-spam-filtering-an-implementation-with-python-and-scikit-learn.html
###############################################################################

import json
import argparse
import re
import os
import joblib
import sqlite3 as sql
import numpy as np
from datetime import datetime
from collections import Counter
from sklearn.naive_bayes import MultinomialNB, GaussianNB, BernoulliNB
from sklearn.svm import SVC, NuSVC, LinearSVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, KFold
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import KNeighborsClassifier
from sklearn.metrics import confusion_matrix, classification_report
from nltk.corpus import stopwords
import networkx as nx
import network_graph as ng

stops = set(stopwords.words("english"))

def graph_features(from_address, to_address, G, cur):
    features = []
    from_ind = ng.email_address_index(cur, from_address)
    to_ind = ng.email_address_index(cur, to_address)

    # See if the sender email address is a pure sender or actually has received emails as well
    sender_ratio = G.in_degree(from_ind) / (G.out_degree(from_ind) + 0.1)

    # See if there is a path from the recipient to the sender, get length of shortest such path
    from_to_path = int(nx.has_path(G, from_ind, to_ind))

    #Do we need path length at all?
    if from_to_path:
        from_to_path_len = nx.shortest_path_length(G, from_ind, to_ind)
    else:
        # Should this be none, or e.g. set
        from_to_path_len = None

    # More features from user graph?

    return features

def featurize_email(email_json, word_indices, cur, G):
    n_subsections = len(email_json["body"])
    email_addresses = []
    jpl_addresses = []
    outside_addresses = []
    i = 0
    while i < n_subsections:
        try:
            email_addresses = email_json["body"][i]["email"]
        except:
            i += 1
            continue
        break
    if email_addresses == []:
        print("No email addresses found")
        i = 0
    # Divide email addresses into JPL and non-JPL
    for address in email_addresses:
        if re.search("nasa.gov", address) is not None:
            jpl_addresses.append(address)
        # I don't think we want to count intermediate apache routing things
        elif re.search("apache", address) is not None:
            outside_addresses.append(address)
    n_jpl = len(jpl_addresses)
    n_outside = len(outside_addresses)

    try:
        content = email_json["body"][i]["content"]
    except:
        print(email_json["body"])
        print(i)
        raise
    subject = content.split("Subject: ")[-1].split("\n")[0]
    subj_chars = len(subject)
    subj_words = len(subject.split(" "))

    content_type = email_json["body"][0]["content_type"]

    # See if there are links
    n_links = 0
    for item in email_json["body"]:
        if "uri" in item:
            n_links += len(item["uri"])

    if "attachments" in email_json:
        n_attachments = len(email_json["attachments"])
    else:
        n_attachments = 0

    # Make a one-hot variable the set of extensions.
    extensions = ['jpg', 'png', 'p7m', 'none', 'txt', 'htm', 'pdf', 'docx',
                  'ics', 'gif', 'bmp', 'pptx', 'doc', 'zip', 'xls', 'xlsx',
                  'html', 'aspx', 'xml', 'jar', 'rar', 'tiff', '05', 'jpeg',
                  'ace', 'wav', 'm4a', 'vcf', '3gp', 'avi']
    extension_indices = {}
    # Build index reference dictionary
    for i in range(0, len(extensions)):
        extension_indices[extensions[i]] = i
    # Might make this a numpy array...
    att_extensions = [0] * len(extensions)
    att_sizes = []
    if n_attachments > 0:
        for attachment in email_json["attachments"]:
            if "extension" not in attachment:
                att_extensions[extension_indices["none"]] += 1
            else:
                att_extensions[extension_indices[attachment["extension"]]] += 1

    # Encode occurence in this email of the top words from the whole set.
    words = []
    for item in email_json["body"]:
        temp_words = item["content"].split()
        for word in temp_words:
            # Cull some things we don't want. Very long words are probably links and such
            # May also want to cut out stop words here.
            if len(word) > 15 or re.search(":", word) is not None or word.isalpha() is False or word in stops:
                continue
            words.append(word)
    word_counter = Counter(words)
    encoded_words = [0] * len(word_indices)
    for word in word_counter.items():
        if word[0] in word_indices:
            encoded_words[word_indices[word[0]]] = word[1]

    # Get features from email network graph structure/user state
    graph_features = graph_features(from_email, to_email, G, cur)

    return np.array(att_extensions + [n_jpl, n_outside, subj_chars, subj_words, n_links] + graph_features + encoded_words)

###############################################################################

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--model", type = str, default = "SVM",
                        help = "Model to use for classification")
    parser.add_argument("-w", "--words", type = str, help = "Word dictionary (well, list) json file")
    parser.add_argument("-f", "--features", type = str,
            help = "Numpy save file with feature matrix. Must also specify labels file")
    parser.add_argument("-l", "--labels", type = str,
            help = "Numpy save file with label vector. Must also specify features file")
    parser.add_argument("-g", "--graph", type = str,
            help = "Pickled network graph of connections between email addresses")
    args = parser.parse_args()

    function_key = {"SVC": LinearSVC(),
                    "NB": MultinomialNB(),
                    "KNN": KNeighborsClassifier(n_neighbors=5),
                    "RF": RandomForestClassifier()}

    # Note: I'm putting the Credential Phishing and Phishing Training emails both under Phishing
    type_labels = {"Not Spam": 0,
                   "Malware": 1,
                   "Phishing": 2,
                   "Propaganda": 3,
                   "Recon": 4,
                   "Social Engineering": 5,
                   "Spam": 6}

    # Get filenames from database
    #conn = sql.connect("/home/user-data/mail/jpl_emails.sqlite")
    conn = sql.connect("/home/rosteen/Work/seemail/jpl_emails.sqlite")
    cur = conn.cursor()
    filenames = []
    res = cur.execute("select * from abuse").fetchall()
    for row in res:
        filenames.append(row[2])

    print(filenames[0])

    # Load list of words for word frequency features
    if args.words:
        word_indices = {}
        with open(args.words, "r") as f:
            word_list = json.load(f)
        # Might be (probably) a list of (word, count) pairs. Take just the words
        if type(word_list[0]) == list:
            word_list = [x[0] for x in word_list]
        for i in range(0, len(word_list)):
            word_indices[word_list[i]] = i
        print("Loaded word dictionary of {} words".format(len(word_list)))

    # Load email network graph
    G = nx.read_pickle(args.graph)

    # Parse all the emails to create training/test matrices and labels
    feature_matrix = []
    labels = []
    n = 0
    for fname in filenames:
        str_label = fname.split("/")[-2]
        if str_label == "Unknown":
            continue
        elif re.search("Phishing", str_label) is not None:
            str_label = "Phishing"
        elif str_label == "False Positive":
            str_label = "Not Spam"
        with open(fname, "r") as f:
            email_json = json.load(f)
        if not args.features:
            features = featurize_email(email_json, word_indices, cur, G)
            if feature_matrix == []:
                feature_matrix = features
            else:
                # Figure out best way to stack
                feature_matrix = np.vstack([feature_matrix, features])
            labels.append(type_labels[str_label])
        n += 1
        if n % 1000 == 0:
            print("{} : Processed {} files".format(datetime.now(), n))

    if args.features:
        feature_matrix = np.load(args.features)
        labels = np.load(args.labels)
    else:
        labels = np.array(labels)

    print("Created feature matrix and labels")
    np.save("feature_matrix.npy", feature_matrix)
    np.save("label_vector.npy", labels)

    # Split data to train and test and scale
    #X_train, X_test, y_train, y_test = train_test_split(feature_matrix, labels, test_size = 0.4)
    kf = KFold(n_splits = 5, shuffle = True)
    kf.get_n_splits(feature_matrix)
    for train_index, test_index in kf.split(feature_matrix):
        X_train, X_test = feature_matrix[train_index,], feature_matrix[test_index]
        y_train, y_test = labels[train_index,], labels[test_index]

        if args.model in ("SVC", "KNN", "RF"):
            scaler = StandardScaler().fit(X_train)
            X_train = scaler.transform(X_train)
            X_test = scaler.transform(X_test)

        # Train the chosen model
        print("Training model")
        model = function_key[args.model].fit(X_train, y_train)

        # Run test on the trained model to check performance
        print("Making predictions for test set")
        res = model.predict(X_test)
        print(confusion_matrix(y_test, res))
        print(classification_report(y_test, res))
    
    # Save out the last kfold 
    joblib.dump(model, "trained_model.joblib")
