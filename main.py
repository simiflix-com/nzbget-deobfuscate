#!/usr/bin/env python
#
# DeobfuscationSort post-processing script for NZBGet.
#
# Copyright (C) 2025 Simi Flix <simiflix@gmail.com>
# Copyright (C) 2013-2020 Andrey Prygunkov <hugbug@users.sourceforge.net>
# Copyright (C) 2024 Denis <denis@nzbget.com>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.    See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with the program.  If not, see <https://www.gnu.org/licenses/>.
#


from pathlib import Path
import sys
from os.path import dirname

sys.path.insert(0, dirname(__file__) + "/lib")
sys.stdout.reconfigure(encoding="utf-8")

import os
import traceback
import re
import shutil
import guessit
import difflib
import locale
import glob

try:
    unicode
except NameError:
    unicode = str

# Exit codes used by NZBGet
POSTPROCESS_SUCCESS = 93
POSTPROCESS_NONE = 95
POSTPROCESS_ERROR = 94


# Logging helpers for consistent message formatting
def log_to_nzbget(msg, dest="DETAIL"):
    print(f"[{dest}] {msg}")

def logdet(msg):
    return log_to_nzbget(msg, "DETAIL")

def loginf(msg):
    return log_to_nzbget(msg, "INFO")

def logwar(msg):
    return log_to_nzbget(msg, "WARNING")

def logerr(msg):
    return log_to_nzbget(msg, "ERROR")


# Check if directory still exist (for post-process again)
if not os.path.exists(os.environ["NZBPP_DIRECTORY"]):
    print(
        "[INFO] Destination directory %s doesn't exist, exiting"
        % os.environ["NZBPP_DIRECTORY"]
    )
    sys.exit(POSTPROCESS_NONE)

# Check par and unpack status for errors
if (
    os.environ["NZBPP_PARSTATUS"] == "1"
    or os.environ["NZBPP_PARSTATUS"] == "4"
    or os.environ["NZBPP_UNPACKSTATUS"] == "1"
):
    print(
        '[WARNING] Download of "%s" has failed, exiting' % (os.environ["NZBPP_NZBNAME"])
    )
    sys.exit(POSTPROCESS_NONE)

# Check if all required script config options are present in config file
required_options = (
    "NZBPO_MoviesDir",
    "NZBPO_SeriesDir",
    "NZBPO_DatedDir",
    "NZBPO_OtherTvDir",
    "NZBPO_VideoExtensions",
    "NZBPO_SatelliteExtensions",
    "NZBPO_MinSize",
    "NZBPO_MoviesFormat",
    "NZBPO_SeriesFormat",
    "NZBPO_OtherTvFormat",
    "NZBPO_DatedFormat",
    "NZBPO_EpisodeSeparator",
    "NZBPO_Overwrite",
    "NZBPO_Cleanup",
    "NZBPO_LowerWords",
    "NZBPO_UpperWords",
    "NZBPO_DeObfuscateWords",
    "NZBPO_ReleaseGroups",
    "NZBPO_TvCategories",
    "NZBPO_Preview",
    "NZBPO_Verbose",
)
for optname in required_options:
    if not optname.upper() in os.environ:
        print(
            "[ERROR] Option %s is missing in configuration file. Please check script settings"
            % optname[6:]
        )
        sys.exit(POSTPROCESS_ERROR)

# Init script config options
nzb_name = os.environ["NZBPP_NZBNAME"]
download_dir = os.environ["NZBPP_DIRECTORY"]
movies_format = os.environ["NZBPO_MOVIESFORMAT"]
series_format = os.environ["NZBPO_SERIESFORMAT"]
dated_format = os.environ["NZBPO_DATEDFORMAT"]
othertv_format = os.environ["NZBPO_OTHERTVFORMAT"]
multiple_episodes = os.environ["NZBPO_MULTIPLEEPISODES"]
episode_separator = os.environ["NZBPO_EPISODESEPARATOR"]
movies_dir = os.environ["NZBPO_MOVIESDIR"]
series_dir = os.environ["NZBPO_SERIESDIR"]
dated_dir = os.environ["NZBPO_DATEDDIR"]
othertv_dir = os.environ["NZBPO_OTHERTVDIR"]
video_extensions = (
    os.environ["NZBPO_VIDEOEXTENSIONS"].replace(" ", "").lower().split(",")
)
satellite_extensions = (
    os.environ["NZBPO_SATELLITEEXTENSIONS"].replace(" ", "").lower().split(",")
)
min_size = int(os.environ["NZBPO_MINSIZE"])
min_size <<= 20
overwrite = os.environ["NZBPO_OVERWRITE"] == "yes"
overwrite_smaller = os.environ["NZBPO_OVERWRITESMALLER"] == "yes"
cleanup = os.environ["NZBPO_CLEANUP"] == "yes"
preview = os.environ["NZBPO_PREVIEW"] == "yes"
verbose = os.environ["NZBPO_VERBOSE"] == "yes"
satellites = len(satellite_extensions) > 0
lower_words = os.environ["NZBPO_LOWERWORDS"].replace(" ", "").split(",")
upper_words = os.environ["NZBPO_UPPERWORDS"].replace(" ", "").split(",")
deobfuscate_words = os.environ["NZBPO_DEOBFUSCATEWORDS"].replace(" ", "").split(",")
release_groups = os.environ["NZBPO_RELEASEGROUPS"].replace(" ", "").split(",")
series_year = os.environ.get("NZBPO_SERIESYEAR", "yes") == "yes"

tv_categories = os.environ["NZBPO_TVCATEGORIES"].lower().split(",")
category = os.environ.get("NZBPP_CATEGORY", "")
force_tv = category.lower() in tv_categories

dnzb_headers = os.environ.get("NZBPO_DNZBHEADERS", "yes") == "yes"
dnzb_proper_name = os.environ.get("NZBPR__DNZB_PROPERNAME", "")
dnzb_episode_name = os.environ.get("NZBPR__DNZB_EPISODENAME", "")
dnzb_movie_year = os.environ.get("NZBPR__DNZB_MOVIEYEAR", "")
dnzb_more_info = os.environ.get("NZBPR__DNZB_MOREINFO", "")
prefer_nzb_name = os.environ.get("NZBPO_PREFERNZBNAME", "") == "yes"
use_nzb_name = False

# NZBPO_DNZBHEADERS must also be enabled
deep_scan = dnzb_headers
# difflib match threshold. Anything below is not considered a match
deep_scan_ratio = 0.60


if len(deobfuscate_words) and len(deobfuscate_words[0]):
    # if verbose:
    #     print('De-obfuscation words: "{}"'.format(" | ".join(deobfuscate_words)))
    deobfuscate_re = re.compile(r"(.+?-[.0-9a-z]+)(?:\W+(?:{})[a-z0-9]*\W*)*$".format("|".join([re.escape(word) for word in deobfuscate_words])), re.IGNORECASE)
else:
    deobfuscate_re = re.compile(r"""
        ^(.+? # Minimal length match for anything other than "-"
        [-][.0-9a-z]+) # "-" followed by alphanumeric and dot indicates name of release group
        .*$ # Anything that is left is considered deobfuscation and will be stripped
    """, flags=re.VERBOSE | re.IGNORECASE)

# if verbose:
#     print('De-obfuscation regex: "{}"'.format(deobfuscate_re.pattern))

if preview:
    print("[WARNING] *** PREVIEW MODE ON - NO CHANGES TO FILE SYSTEM ***")

if verbose and force_tv:
    print("[INFO] Forcing TV sorting (category: %s)" % category)

# List of moved files (source path)
moved_src_files = []

# List of moved files (destination path)
moved_dst_files = []

# Separator character used between file name and opening brace
# for duplicate files such as "My Movie (2).mkv"
dupe_separator = " "


class deprecation_support:
    """Class implementing iterator for deprecation message support"""

    def __init__(self, mapping):
        self.iter = iter(mapping)

    def __iter__(self):
        return self

    def __next__(self):
        map_entry = next(self.iter)
        return map_entry if len(map_entry) >= 3 else list(map_entry) + [None]

    def next(self):
        return self.__next__()


def guess_dupe_separator(format):
    """Find out a char most suitable as dupe_separator"""
    global dupe_separator

    dupe_separator = " "
    format_fname = os.path.basename(format)

    for x in ("%.t", "%s.n", "%s.N"):
        if format_fname.find(x) > -1:
            dupe_separator = "."
            return

    for x in ("%_t", "%s_n", "%s_N"):
        if format_fname.find(x) > -1:
            dupe_separator = "_"
            return


def unique_name(new):
    """Adds unique numeric suffix to destination file name to avoid overwriting
    such as "filename.(2).ext", "filename.(3).ext", etc.
    If existing file was created by the script it is renamed to "filename.(1).ext".
    """
    fname, fext = os.path.splitext(new)
    suffix_num = 2
    while True:
        new_name = fname + dupe_separator + "(" + str(suffix_num) + ")" + fext
        if not os.path.exists(new_name) and new_name not in moved_dst_files:
            break
        suffix_num += 1
    return new_name


def optimized_move(old, new):
    try:
        os.rename(old, new)
    except OSError as ex:
        print("[DETAIL] Rename failed ({}), performing copy: {}".format(ex, new))
        shutil.copyfile(old, new)
        os.remove(old)


def rename(old, new):
    """Moves the file to its sorted location.
    It creates any necessary directories to place the new file and moves it.
    """
    if os.path.exists(new) or new in moved_dst_files:
        if overwrite and new not in moved_dst_files:
            os.remove(new)
            optimized_move(old, new)
            print("[INFO] Overwrote: %s" % new)
        else:
            # rename to filename.(2).ext, filename.(3).ext, etc.
            new = unique_name(new)
            rename(old, new)
    else:
        if not preview:
            if not os.path.exists(os.path.dirname(new)):
                os.makedirs(os.path.dirname(new))
            optimized_move(old, new)
        print("[INFO] Moved: %s" % new)
    moved_src_files.append(old)
    moved_dst_files.append(new)
    return new


def move_satellites(videofile, dest):
    """Moves satellite files such as subtitles that are associated with base
    and stored in root to the correct dest.
    """
    if verbose:
        print("Move satellites for %s" % videofile)

    root = os.path.dirname(videofile)
    destbasenm = os.path.splitext(dest)[0]
    base = os.path.basename(os.path.splitext(videofile)[0])
    for dirpath, dirnames, filenames in os.walk(root):
        for filename in filenames:
            fbase, fext = os.path.splitext(filename)
            fextlo = fext.lower()
            fpath = os.path.join(dirpath, filename)

            if fextlo in satellite_extensions:
                # Handle subtitles and nfo files
                subpart = ""
                # We support GuessIt supported subtitle extensions
                if fextlo[1:] in ["srt", "idx", "sub", "ssa", "ass"]:
                    guess = guessit.guessit(filename)
                    if guess and "subtitle_language" in guess:
                        fbase = fbase[: fbase.rfind(".")]
                        # Use alpha2 subtitle language from GuessIt (en, es, de, etc.)
                        subpart = "." + guess["subtitle_language"].alpha2
                    if verbose:
                        if subpart != "":
                            print(
                                "Satellite: %s is a subtitle [%s]"
                                % (filename, guess["subtitle_language"])
                            )
                        else:
                            # English (or undetermined)
                            print("Satellite: %s is a subtitle" % filename)
                elif (fbase.lower() != base.lower()) and fextlo == ".nfo":
                    # Aggressive match attempt
                    if deep_scan:
                        guess = deep_scan_nfo(fpath)
                        if guess is not None:
                            # Guess details are not important, just that there was a match
                            fbase = base
                if fbase.lower() == base.lower():
                    old = fpath
                    new = destbasenm + subpart + fext
                    if verbose:
                        print("Satellite: %s" % os.path.basename(new))
                    rename(old, new)


def deep_scan_nfo(filename, ratio=deep_scan_ratio):
    if verbose:
        print("Deep scanning satellite: %s (ratio=%.2f)" % (filename, ratio))
    best_guess = None
    best_ratio = 0.00
    try:
        nfo = open(filename)
        # Convert file content into iterable words
        for word in "".join([item for item in nfo.readlines()]).split():
            try:
                guess = guessit.guessit(word + ".nfo")
                # Series = TV, Title = Movie
                if any(item in guess for item in ("title")):
                    # Compare word against NZB name
                    diff = difflib.SequenceMatcher(None, word, nzb_name)
                    # Evaluate ratio against threshold and previous matches
                    if verbose:
                        print("Tested: %s (ratio=%.2f)" % (word, diff.ratio()))
                    if diff.ratio() >= ratio and diff.ratio() > best_ratio:
                        if verbose:
                            print(
                                "Possible match found: %s (ratio=%.2f)"
                                % (word, diff.ratio())
                            )
                        best_guess = guess
                        best_ratio = diff.ratio()
            except UnicodeDecodeError:
                # Ignore non-unicode words (common in nfo "artwork")
                pass
        nfo.close()
    except IOError as e:
        print("[ERROR] %s" % str(e))
    return best_guess


def cleanup_download_dir():
    """Remove the download directory if it (or any subfodler) does not contain "important" files
    (important = size >= min_size)
    """
    if verbose:
        print("Cleanup")

    # Check if there are any big files remaining
    for root, dirs, files in os.walk(download_dir):
        for filename in files:
            path = os.path.join(root, filename)
            # Check minimum file size
            if os.path.getsize(path) >= min_size and (
                not preview or path not in moved_src_files
            ):
                print(
                    "[WARNING] Skipping clean up due to large files remaining in the directory"
                )
                return

    # Now delete all files with nice logging
    for root, dirs, files in os.walk(download_dir):
        for filename in files:
            path = os.path.join(root, filename)
            if not preview or path not in moved_src_files:
                if not preview:
                    os.remove(path)
                print("[INFO] Deleted: %s" % path)
    if not preview:
        shutil.rmtree(download_dir)
    print("[INFO] Deleted: %s" % download_dir)


STRIP_AFTER = ("_", ".", "-")

# * From SABnzbd+ (with modifications) *

REPLACE_AFTER = {
    "()": "",
    "..": ".",
    "__": "_",
    "  ": " ",
    "//": "/",
    " - - ": " - ",
    "--": "-",
}


def path_subst(path, mapping):
    """Replace the sort sting elements by real values.
    Non-elements are copied literally.
    path = the sort string
    mapping = array of tuples that maps all elements to their values
    """
    newpath = []
    plen = len(path)
    n = 0

    # Sort list of mapping tuples by their first elements. First ascending by element,
    # then descending by element length.
    # Preparation to replace elements from longest to shortest in alphabetical order.
    #
    # >>> m = [('bb', 4), ('aa', 3), ('b', 6), ('aaa', 2), ('zzzz', 1), ('a', 5)]
    # >>> m.sort(key=lambda t: t[0])
    # >>> m
    # [('a', 5), ('aa', 3), ('aaa', 2), ('b', 6), ('bb', 4), ('zzzz', 1)]
    # >>> m.sort(key=lambda t: len(t[0]), reverse=True)
    # >>> m
    # [('zzzz', 1), ('aaa', 2), ('aa', 3), ('bb', 4), ('a', 5), ('b', 6)]
    mapping.sort(key=lambda t: t[0])
    mapping.sort(key=lambda t: len(t[0]), reverse=True)

    while n < plen:
        result = path[n]
        if result == "%":
            for key, value, msg in deprecation_support(mapping):
                if path.startswith(key, n):
                    n += len(key) - 1
                    result = value
                    if msg:
                        print("[WARNING] specifier %s is deprecated, %s" % (key, msg))
                    break
        newpath.append(result)
        n += 1
    return "".join(
        map(lambda x: ".".join(x) if isinstance(x, list) else str(x), newpath)
    )


def get_deobfuscated_dirname(dirname, deobfuscate_re, name=None):
    global release_groups
    dirname_clean = dirname.strip()
    dirname = dirname_clean
    if deobfuscate_re:
        dirname_deobfuscated = re.sub(deobfuscate_re, r"\1", dirname_clean)
        dirname = dirname_deobfuscated
        if verbose:
            print('De-obfuscated NZB dirname: "{}" --> "{}"'.format(dirname_clean, dirname_deobfuscated))
    else:
        if verbose:
            print("Cannot de-obfuscate NZB dirname: "
                  'invalid value for configuration value "DeobfuscateWords": "{}"'
                  .format(deobfuscate_words))

    if name:
        # Determine if file name is likely to be properly cased
        case_check_re = r"^[A-Z0-9]+.+\b\d{3,4}p\b.*-[-A-Za-z0-9]+[A-Z]+[-A-Za-z0-9]*$"
        if re.match(case_check_re, dirname):
            loginf(f"Not fixing a properly cased dirname: '{dirname}'")
        else:
            title, _, _ = get_titles(name, True)
            dirname_title = []

            release_groups_list = [re.escape(token) for token in release_groups]
            release_groups_re = "|".join(release_groups_list)

            def re_unescape(escaped_re):
                return re.sub(r"\\(.)", r"\1", escaped_re)

            def scene_group_case(match):
                for extra_group in release_groups_list:
                    loginf(f"Comparing extra group '{extra_group}' with match '{match.group(1)}'")
                    if re.match(f"{extra_group}$", match.group(1), flags=re.IGNORECASE):
                        return "-" + re_unescape(extra_group)
                return "-" + re.sub(r"I", "i", match.group(1).upper())

            terms = [(r"(\d{3,4})p", r"\1p"),
                     (r"x(\d{3,4})", r"x\1"),
                     (r"(\d{2,2}Bit)", r"\1Bit"),
                     (r"BluRay", "BluRay"),
                     (r"Web(.?)DL", r"Web\1DL"),
                     (r"Web(.?)Rip", r"Web\1Rip"),
                     (r"AAC", "AAC"),
                     (r"Dolby", "Dolby"),
                     (r"Atmos", "Atmos"),
                     (r"TrueHD", "TrueHD"),
                     (r"DD([57]).?1", "DD\1.1"),
                     (r"DTS.?X", r"DTS-X"),
                     (r"DTS.?HD", r"DTS-HD"),
                     (r"DTS.?ES", r"DTS-ES"),
                     (r"DTS.?HD.?MA", r"DTS-HD.?MA"),
                     (r"-(([A-Za-z0-9]+)|{})$".format(release_groups_re), scene_group_case)
            ]

            title_match_re = r"(.+?)\b\d{3,4}p\b"
            title_match = re.search(title_match_re, dirname, flags=re.IGNORECASE)
            if title_match:
                title_len = min(len(title_match.group(1)), len(title))
                loginf(f'Comparing dirname "{dirname[0:title_len]}" with titled dirname: "{title[0:title_len]}"')
                for idx in range(title_len):
                    if dirname[idx] != title[idx] and dirname[idx].lower() == title[idx].lower():
                        dirname_title.append(title[idx])
                    else:
                        dirname_title.append(dirname[idx])

                dirname = "".join(dirname_title) + dirname[title_len:]
            else:
                logwar(f'dirname "{dirname}" does not match {title_match_re}"')

            for term in terms:
                dirname = re.sub(term[0], term[1], dirname, flags=re.IGNORECASE)

            loginf(f'Case-fixed dirname: "{dirname}"')

    # The title with spaces replaced by dots
    dots = dirname.replace(" - ", "-").replace(" ",".").replace("_",".")
    dots = dots.replace("(", ".").replace(")",".").replace("..",".").rstrip(".")

    # The dirname with spaces replaced by underscores
    underscores = dirname.replace(" ","_").replace(".","_").replace("__","_").rstrip("_")

    # The dirname with dots and underscores replaced by spaces
    spaces = dirname.replace("_"," ").replace("."," ").replace("  "," ").rstrip(" ")

    return dirname, dots, underscores, spaces


def get_titles(name, titleing=False):
    """
    The title will be the part before the match
    Clean it up and title() it

    ''.title() isn't very good under python so this contains
    a lot of little hacks to make it better and for more control
    """

    # make valid filename
    title = re.sub(r"[\"\:\?\*\\\/\<\>\|]", " ", name)

    if titleing:
        title = titler(
            title
        )  # title the show name so it is in a consistant letter case

        # title applied uppercase to 's Python bug?
        title = title.replace("'S", "'s")

        # Make sure some words such as 'and' or 'of' stay lowercased.
        for x in lower_words:
            xtitled = titler(x)
            title = replace_word(title, xtitled, x)

        # Make sure some words such as 'III' or 'IV' stay uppercased.
        for x in upper_words:
            xtitled = titler(x)
            title = replace_word(title, xtitled, x)

        # Make sure the first letter of the title is always uppercase
        if title:
            title = titler(title[0]) + title[1:]

    # The title with spaces replaced by dots
    dots = title.replace(" - ", "-").replace(" ", ".").replace("_", ".")
    dots = dots.replace("(", ".").replace(")", ".").replace("..", ".").rstrip(".")

    # The title with spaces replaced by underscores
    underscores = (
        title.replace(" ", "_").replace(".", "_").replace("__", "_").rstrip("_")
    )

    return title, dots, underscores


def titler(p):
    """title() replacement
    Python's title() fails with Latin-1, so use Unicode detour.
    """
    if isinstance(p, unicode):
        return p.title()
    elif gUTF:
        try:
            return p.decode("utf-8").title().encode("utf-8")
        except:
            return p.decode("latin-1", "replace").title().encode("latin-1", "replace")
    else:
        return p.decode("latin-1", "replace").title().encode("latin-1", "replace")


def replace_word(input, one, two):
    """Regex replace on just words"""
    regex = re.compile(r"\W(%s)(\W|$)" % one, re.I)
    matches = regex.findall(input)
    if matches:
        for m in matches:
            input = input.replace(one, two)
    return input


def get_decades(year):
    """Return 4 digit and 2 digit decades given 'year'"""
    if year:
        try:
            decade = year[2:3] + "0"
            decade2 = year[:3] + "0"
        except:
            decade = ""
            decade2 = ""
    else:
        decade = ""
        decade2 = ""
    return decade, decade2


_RE_LOWERCASE = re.compile(r"{([^{]*)}")


def to_lowercase(path):
    """Lowercases any characters enclosed in {}"""
    while True:
        m = _RE_LOWERCASE.search(path)
        if not m:
            break
        path = path[: m.start()] + m.group(1).lower() + path[m.end() :]

    # just incase
    path = path.replace("{", "")
    path = path.replace("}", "")
    return path


_RE_UPPERCASE = re.compile(r"{{([^{]*)}}")


def to_uppercase(path):
    """Lowercases any characters enclosed in {{}}"""
    while True:
        m = _RE_UPPERCASE.search(path)
        if not m:
            break
        path = path[: m.start()] + m.group(1).upper() + path[m.end() :]
    return path


def strip_folders(path):
    """Return 'path' without leading and trailing strip-characters in each element"""
    f = path.strip("/").split("/")

    # For path beginning with a slash, insert empty element to prevent loss
    if len(path.strip()) > 0 and path.strip()[0] in "/\\":
        f.insert(0, "")

    def strip_all(x):
        """Strip all leading/trailing underscores and hyphens
        also dots for Windows
        """
        old_name = ""
        while old_name != x:
            old_name = x
            for strip_char in STRIP_AFTER:
                x = x.strip().strip(strip_char)

        return x

    return os.path.normpath("/".join([strip_all(x) for x in f]))


gUTF = False
try:
    if sys.platform == "darwin":
        gUTF = True
    else:
        gUTF = locale.getlocale()[1] == "UTF-8"
except:
    # Incorrect locale implementation, assume the worst
    gUTF = False

# END * From SABnzbd+ * END


def add_common_mapping(old_filename, guess, mapping):

    # Original dir name, file name and extension
    original_dirname = os.path.basename(download_dir)
    original_fname, original_fext = os.path.splitext(
        os.path.split(os.path.basename(old_filename))[1]
    )
    original_category = os.environ.get("NZBPP_CATEGORY", "")

    # Directory name
    title_name = original_dirname.replace("-", " ").replace(".", " ").replace("_", " ")
    fname_tname, fname_tname_two, fname_tname_three = get_titles(title_name, True)
    fname_name, fname_name_two, fname_name_three = get_titles(title_name, False)
    mapping.append(("%dn", original_dirname))
    mapping.append(("%^dn", fname_tname))
    mapping.append(("%.dn", fname_tname_two))
    mapping.append(("%_dn", fname_tname_three))
    mapping.append(("%^dN", fname_name))
    mapping.append(("%.dN", fname_name_two))
    mapping.append(("%_dN", fname_name_three))

    # File name
    title_name = original_fname.replace("-", " ").replace(".", " ").replace("_", " ")
    fname_tname, fname_tname_two, fname_tname_three = get_titles(title_name, True)
    fname_name, fname_name_two, fname_name_three = get_titles(title_name, False)
    mapping.append(("%fn", original_fname))
    mapping.append(("%^fn", fname_tname))
    mapping.append(("%.fn", fname_tname_two))
    mapping.append(("%_fn", fname_tname_three))
    mapping.append(("%^fN", fname_name))
    mapping.append(("%.fN", fname_name_two))
    mapping.append(("%_fN", fname_name_three))

    # File extension
    mapping.append(("%ext", original_fext))
    mapping.append(("%EXT", original_fext.upper()))
    mapping.append(("%Ext", original_fext.title()))

    # Category
    category_tname, category_tname_two, category_tname_three = get_titles(
        original_category, True
    )
    category_name, category_name_two, category_name_three = get_titles(
        original_category, False
    )
    mapping.append(("%cat", category_tname))
    mapping.append(("%.cat", category_tname_two))
    mapping.append(("%_cat", category_tname_three))
    mapping.append(("%cAt", category_name))
    mapping.append(("%.cAt", category_name_two))
    mapping.append(("%_cAt", category_name_three))

    # Video information
    mapping.append(("%qf", guess.get("source", "")))
    mapping.append(("%qss", guess.get("screen_size", "")))
    mapping.append(("%qvc", guess.get("video_codec", "")))
    mapping.append(("%qac", guess.get("audio_codec", "")))
    mapping.append(("%qah", guess.get("audio_channels", "")))
    mapping.append(("%qrg", guess.get("release_group", "")))

    # De-obfuscated directory name
    deobfuscated_dirname, deobfuscated_dirname_dots, deobfuscated_dirname_underscores, deobfuscated_dirname_spaces = get_deobfuscated_dirname(original_dirname, deobfuscate_re)
    mapping.append(('%ddn', deobfuscated_dirname))
    mapping.append(('%.ddn', deobfuscated_dirname_dots))
    mapping.append(('%_ddn', deobfuscated_dirname_underscores))
    mapping.append(('%^ddn', deobfuscated_dirname_spaces))
    deobfuscated_dirname_titled, deobfuscated_dirname_titled_dots, deobfuscated_dirname_titled_underscores, deobfuscated_dirname_titled_spaces = get_deobfuscated_dirname(original_dirname, deobfuscate_re, title_name)
    mapping.append(('%ddN', deobfuscated_dirname_titled))
    mapping.append(('%.ddN', deobfuscated_dirname_titled_dots))
    mapping.append(('%_ddN', deobfuscated_dirname_titled_underscores))
    mapping.append(('%^ddN', deobfuscated_dirname_titled_spaces))


def add_series_mapping(guess, mapping):

    # Show name
    series = guess.get("title", "")
    show_tname, show_tname_two, show_tname_three = get_titles(series, True)
    show_name, show_name_two, show_name_three = get_titles(series, False)
    mapping.append(("%sn", show_tname))
    mapping.append(("%s.n", show_tname_two))
    mapping.append(("%s_n", show_tname_three))
    mapping.append(("%sN", show_name))
    mapping.append(("%s.N", show_name_two))
    mapping.append(("%s_N", show_name_three))

    # season number
    season_num = str(guess.get("season", ""))
    mapping.append(("%s", season_num))
    mapping.append(("%0s", season_num.rjust(2, "0")))

    # episode names
    title = guess.get("episode_title")
    if title:
        ep_tname, ep_tname_two, ep_tname_three = get_titles(title, True)
        ep_name, ep_name_two, ep_name_three = get_titles(title, False)
        mapping.append(("%en", ep_tname))
        mapping.append(("%e.n", ep_tname_two))
        mapping.append(("%e_n", ep_tname_three))
        mapping.append(("%eN", ep_name))
        mapping.append(("%e.N", ep_name_two))
        mapping.append(("%e_N", ep_name_three))
    else:
        mapping.append(("%en", ""))
        mapping.append(("%e.n", ""))
        mapping.append(("%e_n", ""))
        mapping.append(("%eN", ""))
        mapping.append(("%e.N", ""))
        mapping.append(("%e_N", ""))

    # episode number
    if not isinstance(guess.get("episode"), list):
        episode_num = str(guess.get("episode", ""))
        mapping.append(("%e", episode_num))
        mapping.append(("%0e", episode_num.rjust(2, "0")))
    else:
        # multi episodes
        episodes = [str(item) for item in guess.get("episode")]
        episode_num_all = ""
        episode_num_just = ""
        if multiple_episodes == "range":
            episode_num_all = episodes[0] + episode_separator + episodes[-1]
            episode_num_just = (
                episodes[0].rjust(2, "0")
                + episode_separator
                + episodes[-1].rjust(2, "0")
            )
        else:  # if multiple_episodes == 'list':
            for episode_num in episodes:
                ep_prefix = episode_separator if episode_num_all != "" else ""
                episode_num_all += ep_prefix + episode_num
                episode_num_just += ep_prefix + episode_num.rjust(2, "0")

        mapping.append(("%e", episode_num_all))
        mapping.append(("%0e", episode_num_just))

    # year
    year = str(guess.get("year", ""))
    mapping.append(("%y", year))

    # decades
    decade, decade_two = get_decades(year)
    mapping.append(("%decade", decade))
    mapping.append(("%0decade", decade_two))


def add_movies_mapping(guess, mapping):

    # title
    name = guess.get("title", "")
    ttitle, ttitle_two, ttitle_three = get_titles(name, True)
    title, title_two, title_three = get_titles(name, False)
    mapping.append(("%title", ttitle))
    mapping.append(("%.title", ttitle_two))
    mapping.append(("%_title", ttitle_three))

    # title (short forms)
    mapping.append(("%t", ttitle))
    mapping.append(("%.t", ttitle_two))
    mapping.append(("%_t", ttitle_three))

    mapping.append(("%tT", title))
    mapping.append(("%t.T", title_two))
    mapping.append(("%t_T", title_three))

    # year
    year = str(guess.get("year", ""))
    mapping.append(("%y", year))

    # decades
    decade, decade_two = get_decades(year)
    mapping.append(("%decade", decade))
    mapping.append(("%0decade", decade_two))

    # imdb
    mapping.append(("%imdb", guess.get("imdb", "")))
    mapping.append(("%cpimdb", guess.get("cpimdb", "")))


def add_dated_mapping(guess, mapping):

    # title
    name = guess.get("title", "")
    ttitle, ttitle_two, ttitle_three = get_titles(name, True)
    title, title_two, title_three = get_titles(name, True)
    mapping.append(("%title", title))
    mapping.append(("%.title", title_two))
    mapping.append(("%_title", title_three))

    # title (short forms)
    mapping.append(("%t", title, "consider using %sn"))
    mapping.append(("%.t", title_two, "consider using %s.n"))
    mapping.append(("%_t", title_three, "consider using %s_n"))

    # Show name
    series = guess.get("title", "")
    show_tname, show_tname_two, show_tname_three = get_titles(series, True)
    show_name, show_name_two, show_name_three = get_titles(series, False)
    mapping.append(("%sn", show_tname))
    mapping.append(("%s.n", show_tname_two))
    mapping.append(("%s_n", show_tname_three))
    mapping.append(("%sN", show_name))
    mapping.append(("%s.N", show_name_two))
    mapping.append(("%s_N", show_name_three))

    # Some older code at this point stated:
    # "Guessit doesn't provide episode names for dated tv shows"
    # but was referring to the invalid field '%desc'
    # In my researches I couldn't find such a case, but just to be sure
    ep_title = guess.get("episode_title")
    if ep_title:
        ep_tname, ep_tname_two, ep_tname_three = get_titles(ep_title, True)
        ep_name, ep_name_two, ep_name_three = get_titles(ep_title, False)
        mapping.append(("%en", ep_tname))
        mapping.append(("%e.n", ep_tname_two))
        mapping.append(("%e_n", ep_tname_three))
        mapping.append(("%eN", ep_name))
        mapping.append(("%e.N", ep_name_two))
        mapping.append(("%e_N", ep_name_three))
    else:
        mapping.append(("%en", ""))
        mapping.append(("%e.n", ""))
        mapping.append(("%e_n", ""))
        mapping.append(("%eN", ""))
        mapping.append(("%e.N", ""))
        mapping.append(("%e_N", ""))

    # date
    date = guess.get("date")

    # year
    year = str(date.year)
    mapping.append(("%year", year))
    mapping.append(("%y", year))

    # decades
    decade, decade_two = get_decades(year)
    mapping.append(("%decade", decade))
    mapping.append(("%0decade", decade_two))

    # month
    month = str(date.month)
    mapping.append(("%m", month))
    mapping.append(("%0m", month.rjust(2, "0")))

    # day
    day = str(date.day)
    mapping.append(("%d", day))
    mapping.append(("%0d", day.rjust(2, "0")))


def os_path_split(path):
    parts = []
    while True:
        newpath, tail = os.path.split(path)
        if newpath == path:
            if path:
                parts.append(path)
            break
        parts.append(tail)
        path = newpath
    parts.reverse()
    return parts


def deobfuscate_path(filename):
    start = os.path.dirname(download_dir)
    new_name = filename[len(start) + 1 :]
    if verbose:
        print("stripped filename: %s" % new_name)

    parts = os_path_split(new_name)
    if verbose:
        print(parts)

    part_removed = 0
    for x in range(0, len(parts) - 1):
        fn = parts[x]
        if fn.find(".") == -1 and fn.find("_") == -1 and fn.find(" ") == -1:
            print(
                "Detected obfuscated directory name %s, removing from guess path" % fn
            )
            parts[x] = None
            part_removed += 1

    fn = os.path.splitext(parts[len(parts) - 1])[0]
    if fn.find(".") == -1 and fn.find("_") == -1 and fn.find(" ") == -1:
        print(
            "Detected obfuscated filename %s, removing from guess path"
            % os.path.basename(filename)
        )
        parts[len(parts) - 1] = "-" + os.path.splitext(filename)[1]
        part_removed += 1

    if part_removed < len(parts):
        new_name = ""
        for x in range(0, len(parts)):
            if parts[x] != None:
                new_name = os.path.join(new_name, parts[x])
    else:
        print("All file path parts are obfuscated, using obfuscated NZB-Name")
        new_name = os.path.basename(download_dir) + os.path.splitext(filename)[1]

    return new_name


def remove_year(title):
    """Removes year from series name (if exist)"""
    m = re.compile(r"..*(\((19|20)\d\d\))").search(title)
    if not m:
        m = re.compile(r"..*((19|20)\d\d)").search(title)
    if m:
        if verbose:
            print("Removing year from series name")
        title = title.replace(m.group(1), "").strip()
    return title


def apply_dnzb_headers(guess):
    """Applies DNZB headers (if exist)"""

    dnzb_used = False
    if dnzb_proper_name != "":
        dnzb_used = True
        if verbose:
            print("Using DNZB-ProperName")
        if guess["vtype"] == "series":
            proper_name = dnzb_proper_name
            if not series_year:
                proper_name = remove_year(proper_name)
            guess["title"] = proper_name
        else:
            guess["title"] = dnzb_proper_name

    if dnzb_episode_name != "" and guess["vtype"] == "series":
        dnzb_used = True
        if verbose:
            print("Using DNZB-EpisodeName")
        guess["episode_title"] = dnzb_episode_name

    if dnzb_movie_year != "":
        dnzb_used = True
        if verbose:
            print("Using DNZB-MovieYear")
        guess["year"] = dnzb_movie_year

    if dnzb_more_info != "":
        dnzb_used = True
        if verbose:
            print("Using DNZB-MoreInfo")
        if guess["type"] == "movie":
            regex = re.compile(
                r"^http://www.imdb.com/title/(tt[0-9]+)/$", re.IGNORECASE
            )
            matches = regex.match(dnzb_more_info)
            if matches:
                guess["imdb"] = matches.group(1)
                guess["cpimdb"] = "cp(" + guess["imdb"] + ")"

    if verbose and dnzb_used:
        print(guess)


def year_and_season_equal(guess):
    return (
        guess.get("season")
        and guess.get("year")
        and guess.get("season") == guess.get("year")
    )


def is_movie(guess):
    has_no_episode = guess.get("type") == "episode" and guess.get("episode") == None
    is_movie = (
        has_no_episode
        or guess.get("edition")
        or (year_and_season_equal(guess) and guess.get("type") != "episode")
    )
    return is_movie


def guess_info(filename):
    """Parses the filename using guessit-library"""

    if use_nzb_name:
        if verbose:
            print("Using NZB-Name")
        guessfilename = os.path.basename(download_dir) + os.path.splitext(filename)[1]
    else:
        guessfilename = deobfuscate_path(filename)

    # workaround for titles starting with numbers (which guessit has problems with) (part 1)
    path, tmp_filename = os.path.split(guessfilename)
    pad_start_digits = tmp_filename[0].isdigit()
    if pad_start_digits:
        guessfilename = os.path.join(path, "T" + tmp_filename)

    if verbose:
        print("Guessing: %s" % guessfilename)

    guess = guessit.api.guessit(
        unicode(guessfilename), {"allowed_languages": [], "allowed_countries": []}
    )

    if verbose:
        print(guess)

    # workaround for titles starting with numbers (part 2)
    if pad_start_digits:
        guess["title"] = guess["title"][1:]
        if guess["title"] == "":
            guess["title"] = os.path.splitext(os.path.basename(guessfilename))[0][1:]
            if verbose:
                print("use filename as title for recovery")

    # fix some strange guessit guessing:
    # if guessit doesn't find a year in the file name it thinks it is episode,
    # but we prefer it to be handled as movie instead

    if is_movie(guess):
        guess["type"] = "movie"
        if verbose:
            print("episode without episode-number is a movie")

    # treat parts as episodes ("Part.2" or "Part.II")
    if guess.get("type") == "movie" and guess.get("part") != None:
        guess["type"] = "episode"
        guess["episode"] = guess.get("part")
        if verbose:
            print("treat parts as episodes")

    # add season number if not present
    if guess["type"] == "episode" and (
        guess.get("season") == None or year_and_season_equal(guess)
    ):
        guess["season"] = 1
        if verbose:
            print("force season 1")

    # detect if year is part of series name
    if guess["type"] == "episode":
        if series_year:
            if (
                guess.get("year") != None
                and guess.get("title") != None
                and guess.get("season") != guess.get("year")
                and guess["title"] == remove_year(guess["title"])
            ):
                guess["title"] += " " + str(guess["year"])
                if verbose:
                    print("year is part of title")
        else:
            guess["title"] = remove_year(guess["title"])

    if guess["type"] == "movie":
        date = guess.get("date")
        if date:
            guess["vtype"] = "dated"
        elif force_tv:
            guess["vtype"] = "othertv"
        else:
            guess["vtype"] = "movie"
    elif guess["type"] == "episode":
        guess["vtype"] = "series"
    else:
        guess["vtype"] = guess["type"]

    if dnzb_headers:
        apply_dnzb_headers(guess)

    if verbose:
        print("Type: %s" % guess["vtype"])

    if verbose:
        print(guess)

    return guess


def construct_path(filename):
    """Parses the filename and generates new name for renaming"""

    if verbose:
        print("filename: %s" % filename)

    guess = guess_info(filename)
    type = guess.get("vtype")
    mapping = []
    add_common_mapping(filename, guess, mapping)

    if type == "movie":
        dest_dir = movies_dir
        format = movies_format
        add_movies_mapping(guess, mapping)
    elif type == "series":
        dest_dir = series_dir
        format = series_format
        add_series_mapping(guess, mapping)
    elif type == "dated":
        dest_dir = dated_dir
        format = dated_format
        add_dated_mapping(guess, mapping)
    elif type == "othertv":
        dest_dir = othertv_dir
        format = othertv_format
        add_movies_mapping(guess, mapping)
    else:
        if verbose:
            print("Could not determine video type for %s" % filename)
        return None

    if dest_dir == "":
        dest_dir = os.path.dirname(download_dir)

    # Find out a char most suitable as dupe_separator
    guess_dupe_separator(format)

    # Add extension specifier if the format string doesn't end with it
    if format.rstrip("}")[-5:] != ".%ext":
        format += ".%ext"

    sorter = format.replace("\\", "/")

    if verbose:
        print("format: %s" % sorter)

    # Replace elements
    path = path_subst(sorter, mapping)

    if verbose:
        print("path after subst: %s" % path)

    # Cleanup file name
    old_path = ""
    while old_path != path:
        old_path = path
        for key, name in REPLACE_AFTER.items():
            path = path.replace(key, name)

    path = path.replace("%up", "..")

    # Uppercase all characters encased in {{}}
    path = to_uppercase(path)

    # Lowercase all characters encased in {}
    path = to_lowercase(path)

    # Strip any extra strippable characters around foldernames and filename
    path, ext = os.path.splitext(path)
    path = strip_folders(path)
    path = path + ext

    path = os.path.normpath(path)
    dest_dir = os.path.normpath(dest_dir)

    if verbose:
        print("path after cleanup: %s" % path)

    new_path = os.path.join(dest_dir, *path.split(os.sep))

    if verbose:
        print("destination path: %s" % new_path)

    if filename.upper() == new_path.upper():
        if verbose:
            print("Destination path equals filename  - return None")
        return None

    return new_path


def construct_filename_glob(dest_path):
    """Parses the destination path and generates a glob pattern to detect existing files"""

    dest_file = str(dest_path)
    # Get the filename component of the destination path without the directory and extension
    dest_filename = dest_path.stem

    guess = guess_info(dest_file)
    # properties = guessit.api.properties(unicode(dest_file))

    identifying_filename_components = [
        "title",
        "season",
        "episode",
        "year",
        "edition",
        "part",
        "date",
    ]
  
    # Replace non-identifying components by wildcard character `*`
    filename_glob = ""
    identifying_spans = []
    for component in identifying_filename_components:
        value = guess.get(component, None)
        if value: 
            match = re.search(re.escape(str(value)), dest_filename, re.IGNORECASE)
            if match:
                identifying_spans.append(match.span())
    
    last_end = 0
    for span in sorted(identifying_spans, key=lambda x: x[0]):
        # Add the part of the destination filename referenced by the span
        # If there is a gap between the last span and this one, add a wildcard character
        if span[0] > last_end:
            filename_glob += "*" # + dest_filename[last_end:span[0]]
        filename_glob += dest_filename[span[0]:span[1]]
        last_end = span[1]
    if last_end < len(dest_filename):
        filename_glob += "*" # + dest_filename[last_end:]
    
    dest_path_glob = dest_path.parent / (filename_glob + dest_path.suffix)

    loginf(f'construct_filename_glob("{dest_path}"): "{dest_path_glob}"')

    return dest_path_glob

def rename_overwrite_smaller(old, new):
    old_size = os.path.getsize(old)
    # Create a glob pattern to match all files with the same title and year
    filename_glob = construct_filename_glob(Path(new))
    if verbose:
        loginf('filename_glob: "{}"'.format(filename_glob))
    smallest_size = sys.maxsize
    largest_size = 0
    smallest_file = None
    largest_file = None
    # Use the glob method to iterate through matching files
    for match in filename_glob.parent.glob(filename_glob.name):
        if verbose:
            loginf('checking size of match: "{}"'.format(match))
        match_size = os.path.getsize(match)
        if match_size > largest_size:
            largest_size = match_size
            largest_file = match
            if verbose:
                loginf('match with size {} is now the largest file: "{}"'.format(largest_size, largest_file))
        if match_size < smallest_size:
            smallest_size = match_size
            smallest_file = match
            if verbose:
                loginf('match with size {} is now the smallest file: "{}"'.format(smallest_size, smallest_file))
    if smallest_file:
        if smallest_file != new:
            if old_size > largest_size:
                if verbose:
                    loginf('FIXME: should replace smallest file  "{}" matching glob "{}"'.format(smallest_file, filename_glob))
                # FIXME: This is a dangerous operation. It should be disabled by default.
                # os.remove(smallest_file)
            # FIXME: This is a dangerous operation. It should be disabled by default.
            # else:
            #     if verbose:
            #         loginf('remove downloaded directory: "{}"'.format(download_dir))
            #     shutil.rmtree(download_dir)
        else:
            if verbose:
                loginf('smallest file = new: "{}" = "{}"'.format(smallest_file, new))

    else:
        if verbose:
            loginf('no file matching glob "{}"'.format(filename_glob))

# Flag indicating that anything was moved. Cleanup possible.
files_moved = False

# Flag indicating any error. Cleanup is disabled.
errors = False

# Process all the files in download_dir and its subdirectories
video_files = []

for root, dirs, files in os.walk(download_dir):
    for old_filename in files:
        try:
            old_path = os.path.join(root, old_filename)

            # Check extension
            ext = os.path.splitext(old_filename)[1].lower()
            if ext not in video_extensions:
                continue

            # Check minimum file size
            if os.path.getsize(old_path) < min_size:
                print("[INFO] Skipping small: %s" % old_filename)
                continue

            # This is our video file, we should process it
            video_files.append(old_path)

        except Exception as e:
            errors = True
            print("[ERROR] Failed: %s" % old_filename)
            print("[ERROR] Exception: %s" % e)
            traceback.print_exc()

use_nzb_name = prefer_nzb_name and len(video_files) == 1

for old_path in video_files:
    try:
        new_path = construct_path(old_path)

        if new_path:
            # Move video file
            if overwrite_smaller:
                rename_overwrite_smaller(old_path, new_path)
            else:
                rename(old_path, new_path)

            # Move satellite files
            if satellites:
                move_satellites(old_path, new_path)

    except Exception as e:
        errors = True
        print("[ERROR] Failed: %s" % old_filename)
        print("[ERROR] %s" % e)
        traceback.print_exc()

# Inform NZBGet about new destination path
finaldir = ""
uniquedirs = []
for filename in moved_dst_files:
    dir = os.path.dirname(filename)
    if dir not in uniquedirs:
        uniquedirs.append(dir)
        finaldir += "|" if finaldir != "" else ""
        finaldir += dir

if finaldir != "":
    print("[NZB] FINALDIR=%s" % finaldir)

# Cleanup if:
# 1) files were moved AND
# 2) no errors happen AND
# 3) all remaining files are smaller than <MinSize>
if cleanup and files_moved and not errors:
    cleanup_download_dir()

# Returing status to NZBGet
if errors:
    sys.exit(POSTPROCESS_ERROR)
elif files_moved:
    sys.exit(POSTPROCESS_SUCCESS)
else:
    sys.exit(POSTPROCESS_NONE)
