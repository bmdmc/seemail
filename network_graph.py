#
#  Functions for tracking email interactions via a network graph
#  Graph saved/loaded with pickle
#

import argparse
import networkx as nx
import sqlite3 as sql
import json
from sortedcontainers import SortedList
import sys

# Get the rowid for the email address, adding it to the database if needed
def email_address_index(cur, email_address):
    stmt = "select rowid from email_addresses where address = '{}'".format(email_address)
    res = cur.execute(stmt).fetchall()
    if len(res) == 0:
        stmt = "insert into email_addresses values ({})".format(email_address)
        cur.execute(stmt)
        stmt = "select rowid from email_addresses where address = '{}'".format(email_address)
        res = cur.execute(stmt).fetchall()

    return res[0][0]

# Check if from->to is already an edge and either add it if not, 
# or add timestamp to existing edge
def process_edge(G, from_ind, to_ind, ts):
    if not G.has_edge(from_ind, to_ind):
        G.add_edge(from_ind, to_ind)
        G[from_ind][to_ind]["timestamps"] = sortedlist([ts])
    else:
        G[from_ind][to_ind]["timestamps"].add(ts)
    return G

# Add information to graph from either email file or json data
def process_email(G, filename = None, email_json = None, timestamp = None):
    if filename is not None and email_json is None:
        with open(filename, "r") as f:
            email_json = json.load(f)
    elif email_json is not None and filename is None:
        pass
    else:
        print("Error: Either email filename OR email json must be provided")
        sys.exit(1)
    # NOTE - this will work when we get original emails, for the
    # current set of forwards getting to/from requires more work.
    # Also need to see if cc/bcc show up in to list or separate headers
    from_ind = email_address_index(cur, email_json["header"]["from"])
    # Check to see if there is already a from->to edge in the graph
    # and either add one or add the timestamp to existing edge
    for to_address in email_json["header"]["to"]:
        to_ind = email_address_index(cur, to_address)
        G = process_edge(G, from_ind, to_ind, timestamp)
    
    return G

# Create a new graph from a set of email files
def initialize_graph():
    conn = sql.connect("/home/user-data/mail/jpl_emails.sqlite")
    cur = conn.cursor()
    filenames = []
    timestamps = []
    res = cur.execute("select * from abuse").fetchall()
    for row in res:
        filenames.append(row[2])
        timestamps.append(row[1])
    G = nx.DiGraph()
    
    for i in range(0, len(filenames)):
        G = process_email(G, filename = filenames[i], timestamp = timestamps[i])

    return G

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--create", action = "store_true",
            help = "Flag to create a new graph rather than adding to one")
    parser.add_argument("-g", "--graph", type = str,
            help = "File with existing graph structure")
    args = parser.parse_args()

    # Load previously generated graph or create new one
    if args.create:
        G = initialize_graph()
        nx.write_pickle(G, args.graph)
    else:
        G = nx.read_gpickle(args.graph)
        