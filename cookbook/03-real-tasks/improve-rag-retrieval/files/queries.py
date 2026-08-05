"""Queries and relevance judgments. Protected.

Forty questions phrased the way someone asks them, not the way the docs are
written -- "read a spreadsheet file", not "csv". That mismatch is the retrieval
problem; a query set full of module names would be a keyword-matching problem
and every system would score well on it.

Grades: 2 = this module is the answer, 1 = a reasonable second place.
Judgments are one author's, made before any system was tuned. See the recipe's
"limits" section: forty queries is a demonstration, not an evaluation.
"""

QUERIES = [
    ("read and write comma separated spreadsheet files", {"csv": 2}),
    ("parse a date written as text into an object", {"datetime": 2, "time": 1}),
    ("turn a python dictionary into a string I can save", {"json": 2, "pickle": 1}),
    ("save a python object to disk and load it back", {"pickle": 2, "shelve": 1}),
    ("download a web page from a url", {"urllib": 2, "http": 1}),
    ("run a shell command from python and get its output", {"subprocess": 2, "os": 1}),
    ("find all files matching a wildcard pattern", {"glob": 2, "fnmatch": 1, "pathlib": 1}),
    ("join and split file paths safely", {"posixpath": 2, "pathlib": 2, "os": 1}),
    ("make a temporary file that deletes itself", {"tempfile": 2}),
    ("copy and delete whole directory trees", {"shutil": 2}),
    ("search text for a pattern with wildcards and groups", {"re": 2}),
    ("write messages to a log file with severity levels", {"logging": 2}),
    ("parse command line arguments and flags", {"argparse": 2, "getopt": 1, "optparse": 1}),
    ("read settings from an ini configuration file", {"configparser": 2}),
    ("store data in a local sql database", {"sqlite3": 2, "shelve": 1}),
    ("run several things at once using threads", {"threading": 2, "concurrent": 1}),
    ("run several things at once using separate processes",
     {"multiprocessing": 2, "concurrent": 1}),
    ("write code that waits on network without blocking", {"asyncio": 2, "selectors": 1}),
    ("make a low level network connection to a server", {"socket": 2, "socketserver": 1}),
    ("serve web pages from a simple built in server", {"http": 2, "wsgiref": 1}),
    ("send an email message with an attachment", {"email": 2, "smtplib": 2}),
    ("compress files into a zip archive", {"zipfile": 2, "shutil": 1}),
    ("compress data with gzip", {"gzip": 2, "zlib": 1}),
    ("generate random numbers and shuffle a list", {"random": 2}),
    ("do exact decimal arithmetic for money", {"decimal": 2, "fractions": 1}),
    ("compute statistics like mean and standard deviation", {"statistics": 2}),
    ("hash a password or checksum a file", {"hashlib": 2, "hmac": 1}),
    ("encode binary data as text safely", {"base64": 2, "binascii": 1}),
    ("generate a unique identifier", {"uuid": 2}),
    ("count how many times each item appears in a list", {"collections": 2}),
    ("keep a list sorted as I insert into it", {"bisect": 2, "heapq": 1}),
    ("get the smallest few items from a big list efficiently", {"heapq": 2}),
    ("cache the result of an expensive function call", {"functools": 2}),
    ("loop over combinations and permutations of items", {"itertools": 2}),
    ("measure how long a small piece of code takes", {"timeit": 2, "time": 1}),
    ("find out which functions are slowest in my program",
     {"cProfile": 2, "profile": 2, "pstats": 1}),
    ("step through my code line by line to find a bug", {"pdb": 2, "bdb": 1}),
    ("write and run unit tests", {"unittest": 2, "doctest": 1}),
    ("read the contents of a tar archive", {"tarfile": 2}),
    ("walk a python file's syntax tree programmatically", {"ast": 2, "dis": 1}),
]


def check(doc_ids):
    """Every judged module must exist in the corpus, or the scores lie."""
    missing = sorted(
        {m for _, rel in QUERIES for m in rel} - set(doc_ids)
    )
    if missing:
        raise SystemExit(f"judged modules missing from corpus: {missing}")
