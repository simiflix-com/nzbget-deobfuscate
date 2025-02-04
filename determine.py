import os
import re
from pathlib import Path
from nzbget_utils import loginf, logerr, logwar
from options import Options

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import guessit


# * From SABnzbd+ (with modifications) *
class Determine:
    _STRIP_AFTER = ("_", ".", "-")

    _REPLACE_AFTER = {
        "()": "",
        "..": ".",
        "__": "_",
        "  ": " ",
        "//": "/",
        " - - ": " - ",
        "--": "-",
    }
    _RE_UPPERCASE = re.compile(r"{{([^{]*)}}")
    _RE_LOWERCASE = re.compile(r"{([^{]*)}")

    def __init__(self, options: Options):
        self.options = options

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
                            logwar("specifier %s is deprecated, %s" % (key, msg))
                        break
            newpath.append(result)
            n += 1
        return "".join(
            map(lambda x: ".".join(x) if isinstance(x, list) else str(x), newpath)
        )

    def get_deobfuscated_dirname(self, dirname, deobfuscate_re, name=None):
        dirname_clean = dirname.strip()
        dirname = dirname_clean
        if deobfuscate_re:
            dirname_deobfuscated = re.sub(deobfuscate_re, r"\1", dirname_clean)
            dirname = dirname_deobfuscated
            if self.options.verbose:
                loginf(
                    'De-obfuscated NZB dirname: "{}" --> "{}"'.format(
                        dirname_clean, dirname_deobfuscated
                    )
                )
        else:
            if self.options.verbose:
                logerr(
                    "Cannot de-obfuscate NZB dirname: "
                    'invalid value for configuration value "DeobfuscateWords": "{}"'.format(
                        self.options.deobfuscate_words
                    )
                )

        if name:
            # Determine if file name is likely to be properly cased
            case_check_re = (
                r"^[A-Z0-9]+.+\b\d{3,4}p\b.*-[-A-Za-z0-9]+[A-Z]+[-A-Za-z0-9]*$"
            )
            if re.match(case_check_re, dirname):
                loginf(f"Not fixing a properly cased dirname: '{dirname}'")
            else:
                title, _, _ = self.get_titles(name, True)
                dirname_title = []

                release_groups_list = [
                    re.escape(token) for token in self.options.release_groups
                ]
                release_groups_re = "|".join(release_groups_list)

                def re_unescape(escaped_re):
                    return re.sub(r"\\(.)", r"\1", escaped_re)

                def scene_group_case(match):
                    for extra_group in release_groups_list:
                        loginf(
                            f"Comparing extra group '{extra_group}' with match '{match.group(1)}'"
                        )
                        if re.match(
                            f"{extra_group}$", match.group(1), flags=re.IGNORECASE
                        ):
                            return "-" + re_unescape(extra_group)
                    return "-" + re.sub(r"I", "i", match.group(1).upper())

                terms = [
                    (r"(\d{3,4})p", r"\1p"),
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
                    (
                        r"-(([A-Za-z0-9]+)|{})$".format(release_groups_re),
                        scene_group_case,
                    ),
                ]

                title_match_re = r"(.+?)\b\d{3,4}p\b"
                title_match = re.search(title_match_re, dirname, flags=re.IGNORECASE)
                if title_match:
                    title_len = min(len(title_match.group(1)), len(title))
                    loginf(
                        f'Comparing dirname "{dirname[0:title_len]}" with titled dirname: "{title[0:title_len]}"'
                    )
                    for idx in range(title_len):
                        if (
                            dirname[idx] != title[idx]
                            and dirname[idx].lower() == title[idx].lower()
                        ):
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
        dots = dirname.replace(" - ", "-").replace(" ", ".").replace("_", ".")
        dots = dots.replace("(", ".").replace(")", ".").replace("..", ".").rstrip(".")

        # The dirname with spaces replaced by underscores
        underscores = (
            dirname.replace(" ", "_").replace(".", "_").replace("__", "_").rstrip("_")
        )

        # The dirname with dots and underscores replaced by spaces
        spaces = (
            dirname.replace("_", " ").replace(".", " ").replace("  ", " ").rstrip(" ")
        )

        return dirname, dots, underscores, spaces

    def to_title_case(self, text):
        """
        Improved version of Python's title() function.

        Args:
            text (str): The text to convert to title case

        Returns:
            str: The text in title case
        """
        # Apply Python's built-in title() function
        title = text.title()

        # Fix Python's title() bug with apostrophes
        title = title.replace("'S", "'s")

        # Make sure some words such as 'and' or 'of' stay lowercased
        for x in self.options.lower_words:
            xtitled = x.title()
            title = Determine.replace_word(title, xtitled, x)

        # Make sure some words such as 'III' or 'IV' stay uppercased
        for x in self.options.upper_words:
            xtitled = x.title()
            title = Determine.replace_word(title, xtitled, x)

        # Make sure the first letter of the title is always uppercase
        if title:
            title = title[0].title() + title[1:]

        return title

    def get_titles(self, name, apply_title_case=False):
        """
        Generates three variations of a title with improved title casing.

        Args:
            name (str): The original title name
            apply_title_case (bool): Whether to apply enhanced title casing

        Returns:
            tuple: Three variations of the title (normal, dots, underscores)
        """
        # make valid filename
        title = re.sub(r"[\"\:\?\*\\\/\<\>\|]", " ", name)

        if apply_title_case:
            title = self.to_title_case(title)

        # The title with spaces replaced by dots
        dots = title.replace(" - ", "-").replace(" ", ".").replace("_", ".")
        dots = dots.replace("(", ".").replace(")", ".").replace("..", ".").rstrip(".")

        # The title with spaces replaced by underscores
        underscores = (
            title.replace(" ", "_").replace(".", "_").replace("__", "_").rstrip("_")
        )

        return title, dots, underscores

    @staticmethod
    def replace_word(text, word_old, word_new):
        """
        Replace a word in text while maintaining word boundaries.
        This ensures we only replace whole words, not parts of words.

        Args:
            text (str): The text to process
            word_old (str): The word to find
            word_new (str): The word to replace it with

        Returns:
            str: The text with the word replaced
        """

        def replace_word_case_sensitive(text, word_old, word_new):
            pattern = r"\b" + re.escape(word_old) + r"\b"
            return re.sub(pattern, word_new, text)

        # Try case-sensitive replacement first
        result = replace_word_case_sensitive(text, word_old, word_new)

        # If no replacement was made, try case-insensitive
        if result == text:
            pattern = r"\b" + re.escape(word_old) + r"\b"
            result = re.sub(pattern, word_new, text, flags=re.IGNORECASE)

        return result

    @staticmethod
    def get_decades(year):
        """
        Return 2-digit and 4-digit decades given 'year'.
        For example, for year "2024" or 2024:
        - decade = "20" (2-digit decade)
        - decade2 = "2020" (4-digit decade)

        Args:
            year (Union[str, int]): The year to process

        Returns:
            tuple: Two variations of the decade:
                - decade (str): 2-digit decade (e.g., "20" for 2020s)
                - decade2 (str): 4-digit decade (e.g., "2020" for 2020s)
        """
        if year:
            try:
                year_str = str(year)
                decade = year_str[2:3] + "0"  # Take third digit and add 0 (e.g., "20")
                decade2 = (
                    year_str[:3] + "0"
                )  # Take first three digits and add 0 (e.g., "2020")
            except IndexError:
                decade = ""
                decade2 = ""
        else:
            decade = ""
            decade2 = ""
        return decade, decade2

    @staticmethod
    def to_lowercase(path):
        """Lowercases any characters enclosed in {}"""
        while True:
            m = Determine._RE_LOWERCASE.search(path)
            if not m:
                break
            path = path[: m.start()] + m.group(1).lower() + path[m.end() :]

        # just incase
        path = path.replace("{", "")
        path = path.replace("}", "")
        return path

    @staticmethod
    def to_uppercase(path):
        """Lowercases any characters enclosed in {{}}"""
        while True:
            m = Determine._RE_UPPERCASE.search(path)
            if not m:
                break
            path = path[: m.start()] + m.group(1).upper() + path[m.end() :]
        return path

    @staticmethod
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
                for strip_char in Determine._STRIP_AFTER:
                    x = x.strip().strip(strip_char)

            return x

        return os.path.normpath("/".join([strip_all(x) for x in f]))

    @staticmethod
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

    def add_common_mapping(self, old_filename, guess, mapping):
        # Original dir name, file name and extension
        original_dirname = os.path.basename(self.options.download_dir)
        original_fname, original_fext = os.path.splitext(
            os.path.split(os.path.basename(old_filename))[1]
        )
        original_category = os.environ.get("NZBPP_CATEGORY", "")

        # Directory name
        title_name = (
            original_dirname.replace("-", " ").replace(".", " ").replace("_", " ")
        )
        fname_tname, fname_tname_two, fname_tname_three = self.get_titles(
            title_name, True
        )
        fname_name, fname_name_two, fname_name_three = self.get_titles(
            title_name, False
        )
        mapping.append(("%dn", original_dirname))
        mapping.append(("%^dn", fname_tname))
        mapping.append(("%.dn", fname_tname_two))
        mapping.append(("%_dn", fname_tname_three))
        mapping.append(("%^dN", fname_name))
        mapping.append(("%.dN", fname_name_two))
        mapping.append(("%_dN", fname_name_three))

        # File name
        title_name = (
            original_fname.replace("-", " ").replace(".", " ").replace("_", " ")
        )
        fname_tname, fname_tname_two, fname_tname_three = self.get_titles(
            title_name, True
        )
        fname_name, fname_name_two, fname_name_three = self.get_titles(
            title_name, False
        )
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
        category_tname, category_tname_two, category_tname_three = self.get_titles(
            original_category, True
        )
        category_name, category_name_two, category_name_three = self.get_titles(
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
        (
            deobfuscated_dirname,
            deobfuscated_dirname_dots,
            deobfuscated_dirname_underscores,
            deobfuscated_dirname_spaces,
        ) = self.get_deobfuscated_dirname(original_dirname, self.options.deobfuscate_re)
        mapping.append(("%ddn", deobfuscated_dirname))
        mapping.append(("%.ddn", deobfuscated_dirname_dots))
        mapping.append(("%_ddn", deobfuscated_dirname_underscores))
        mapping.append(("%^ddn", deobfuscated_dirname_spaces))
        (
            deobfuscated_dirname_titled,
            deobfuscated_dirname_titled_dots,
            deobfuscated_dirname_titled_underscores,
            deobfuscated_dirname_titled_spaces,
        ) = self.get_deobfuscated_dirname(
            original_dirname, self.options.deobfuscate_re, title_name
        )
        mapping.append(("%ddN", deobfuscated_dirname_titled))
        mapping.append(("%.ddN", deobfuscated_dirname_titled_dots))
        mapping.append(("%_ddN", deobfuscated_dirname_titled_underscores))
        mapping.append(("%^ddN", deobfuscated_dirname_titled_spaces))

    def add_series_mapping(self, guess, mapping):
        # Show name
        series = guess.get("title", "")
        show_tname, show_tname_two, show_tname_three = self.get_titles(series, True)
        show_name, show_name_two, show_name_three = self.get_titles(series, False)
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
            ep_tname, ep_tname_two, ep_tname_three = self.get_titles(title, True)
            ep_name, ep_name_two, ep_name_three = self.get_titles(title, False)
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
            if self.options.multiple_episodes == "range":
                episode_num_all = (
                    episodes[0] + self.options.episode_separator + episodes[-1]
                )
                episode_num_just = (
                    episodes[0].rjust(2, "0")
                    + self.options.episode_separator
                    + episodes[-1].rjust(2, "0")
                )
            else:  # if multiple_episodes == 'list':
                for episode_num in episodes:
                    ep_prefix = (
                        self.options.episode_separator if episode_num_all != "" else ""
                    )
                    episode_num_all += ep_prefix + episode_num
                    episode_num_just += ep_prefix + episode_num.rjust(2, "0")

            mapping.append(("%e", episode_num_all))
            mapping.append(("%0e", episode_num_just))

        # year
        year = str(guess.get("year", ""))
        mapping.append(("%y", year))

        # decades
        decade, decade_two = self.get_decades(year)
        mapping.append(("%decade", decade))
        mapping.append(("%0decade", decade_two))

    def add_movies_mapping(self, guess, mapping):
        # title
        name = guess.get("title", "")
        ttitle, ttitle_two, ttitle_three = self.get_titles(name, True)
        title, title_two, title_three = self.get_titles(name, False)
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
        decade, decade_two = self.get_decades(year)
        mapping.append(("%decade", decade))
        mapping.append(("%0decade", decade_two))

        # imdb
        mapping.append(("%imdb", guess.get("imdb", "")))
        mapping.append(("%cpimdb", guess.get("cpimdb", "")))

    def add_dated_mapping(self, guess, mapping):
        # title
        name = guess.get("title", "")
        ttitle, ttitle_two, ttitle_three = self.get_titles(name, True)
        title, title_two, title_three = self.get_titles(name, True)
        mapping.append(("%title", title))
        mapping.append(("%.title", title_two))
        mapping.append(("%_title", title_three))

        # title (short forms)
        mapping.append(("%t", title, "consider using %sn"))
        mapping.append(("%.t", title_two, "consider using %s.n"))
        mapping.append(("%_t", title_three, "consider using %s_n"))

        # Show name
        series = guess.get("title", "")
        show_tname, show_tname_two, show_tname_three = self.get_titles(series, True)
        show_name, show_name_two, show_name_three = self.get_titles(series, False)
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
            ep_tname, ep_tname_two, ep_tname_three = self.get_titles(ep_title, True)
            ep_name, ep_name_two, ep_name_three = self.get_titles(ep_title, False)
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
        decade, decade_two = self.get_decades(year)
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

    def strip_useless_parts(self, filename):
        start = os.path.dirname(self.options.download_dir)
        new_name = filename[len(start) + 1 :]
        if self.options.verbose:
            loginf("stripped filename: %s" % new_name)

        parts = Determine.os_path_split(new_name)
        if self.options.verbose:
            loginf(parts)

        part_removed = 0
        for x in range(0, len(parts) - 1):
            fn = parts[x]
            if fn.find(".") == -1 and fn.find("_") == -1 and fn.find(" ") == -1:
                loginf(
                    "Detected obfuscated directory name %s, removing from guess path"
                    % fn
                )
                parts[x] = None
                part_removed += 1

        fn = os.path.splitext(parts[len(parts) - 1])[0]
        if fn.find(".") == -1 and fn.find("_") == -1 and fn.find(" ") == -1:
            loginf(
                "Detected obfuscated filename %s, removing from guess path"
                % os.path.basename(filename)
            )
            parts[len(parts) - 1] = "-" + os.path.splitext(filename)[1]
            part_removed += 1

        if part_removed < len(parts):
            new_name = ""
            for x in range(0, len(parts)):
                if parts[x] is not None:
                    new_name = os.path.join(new_name, parts[x])
        else:
            loginf("All file path parts are obfuscated, using obfuscated NZB-Name")
            new_name = (
                os.path.basename(self.options.download_dir)
                + os.path.splitext(filename)[1]
            )

        return new_name

    def remove_year(self, title):
        """Removes year from series name (if exist)"""
        m = re.compile(r"..*(\((19|20)\d\d\))").search(title)
        if not m:
            m = re.compile(r"..*((19|20)\d\d)").search(title)
        if m:
            if self.options.verbose:
                loginf("Removing year from series name")
            title = title.replace(m.group(1), "").strip()
        return title

    def apply_dnzb_headers(self, guess):
        """Applies DNZB headers (if exist)"""

        dnzb_used = False
        if self.options.dnzb_proper_name != "":
            dnzb_used = True
            if self.options.verbose:
                loginf("Using DNZB-ProperName")
            if guess["vtype"] == "series":
                proper_name = self.options.dnzb_proper_name
                if not self.options.series_year:
                    proper_name = self.remove_year(proper_name)
                guess["title"] = proper_name
            else:
                guess["title"] = self.options.dnzb_proper_name

        if self.options.dnzb_episode_name != "" and guess["vtype"] == "series":
            dnzb_used = True
            if self.options.verbose:
                loginf("Using DNZB-EpisodeName")
            guess["episode_title"] = self.options.dnzb_episode_name

        if self.options.dnzb_movie_year != "":
            dnzb_used = True
            if self.options.verbose:
                loginf("Using DNZB-MovieYear")
            guess["year"] = self.options.dnzb_movie_year

        if self.options.dnzb_more_info != "":
            dnzb_used = True
            if self.options.verbose:
                loginf("Using DNZB-MoreInfo")
            if guess["type"] == "movie":
                regex = re.compile(
                    r"^http://www.imdb.com/title/(tt[0-9]+)/$", re.IGNORECASE
                )
                matches = regex.match(self.options.dnzb_more_info)
                if matches:
                    guess["imdb"] = matches.group(1)
                    guess["cpimdb"] = "cp(" + guess["imdb"] + ")"

        if self.options.verbose and dnzb_used:
            loginf(guess)

    def year_and_season_equal(self, guess):
        return (
            guess.get("season")
            and guess.get("year")
            and guess.get("season") == guess.get("year")
        )

    def is_movie(self, guess):
        has_no_episode = guess.get("type") == "episode" and guess.get("episode") is None
        is_movie = (
            has_no_episode
            or guess.get("edition")
            or (self.year_and_season_equal(guess) and guess.get("type") != "episode")
        )
        return is_movie

    def guess_info(self, filename):
        """Parses the filename using guessit-library"""

        if self.options.use_nzb_name:
            if self.options.verbose:
                loginf("Using NZB-Name")
            guessfilename = (
                os.path.basename(self.options.download_dir)
                + os.path.splitext(filename)[1]
            )
        else:
            guessfilename = self.strip_useless_parts(filename)

        # workaround for titles starting with numbers (which guessit has problems with) (part 1)
        path, tmp_filename = os.path.split(guessfilename)
        pad_start_digits = tmp_filename[0].isdigit()
        if pad_start_digits:
            guessfilename = os.path.join(path, "T" + tmp_filename)

        if self.options.verbose:
            loginf(f'Calling GuessIt with "{guessfilename}"')

        # Use guessit directly as Python 3 handles Unicode by default
        guess = guessit.api.guessit(
            guessfilename, {"allowed_languages": [], "allowed_countries": []}
        )

        if self.options.verbose:
            loginf(guess)

        # workaround for titles starting with numbers (part 2)
        if pad_start_digits:
            guess["title"] = guess["title"][1:]
            if guess["title"] == "":
                guess["title"] = os.path.splitext(os.path.basename(guessfilename))[0][
                    1:
                ]
                if self.options.verbose:
                    loginf("use filename as title for recovery")

        # fix some strange guessit guessing:
        # if guessit doesn't find a year in the file name it thinks it is episode,
        # but we prefer it to be handled as movie instead

        if self.is_movie(guess):
            guess["type"] = "movie"
            if self.options.verbose:
                loginf("episode without episode-number is a movie")

        # treat parts as episodes ("Part.2" or "Part.II")
        if guess.get("type") == "movie" and guess.get("part") is not None:
            guess["type"] = "episode"
            guess["episode"] = guess.get("part")
            if self.options.verbose:
                loginf("treat parts as episodes")

        # add season number if not present
        if guess["type"] == "episode" and (
            guess.get("season") is None or self.year_and_season_equal(guess)
        ):
            guess["season"] = 1
            if self.options.verbose:
                loginf("force season 1")

        # detect if year is part of series name
        if guess["type"] == "episode":
            if self.options.series_year:
                if (
                    guess.get("year") is not None
                    and guess.get("title") is not None
                    and guess.get("season") != guess.get("year")
                    and guess["title"] == self.remove_year(guess["title"])
                ):
                    guess["title"] += " " + str(guess["year"])
                    if self.options.verbose:
                        loginf("year is part of title")
            else:
                guess["title"] = self.remove_year(guess["title"])

        if guess["type"] == "movie":
            date = guess.get("date")
            if date:
                guess["vtype"] = "dated"
            elif self.options.force_tv:
                guess["vtype"] = "othertv"
            else:
                guess["vtype"] = "movie"
        elif guess["type"] == "episode":
            guess["vtype"] = "series"
        else:
            guess["vtype"] = guess["type"]

        if self.options.dnzb_headers:
            self.apply_dnzb_headers(guess)

        if self.options.verbose:
            loginf("Type: %s" % guess["vtype"])

        if self.options.verbose:
            loginf(guess)

        return guess

    def guess_dupe_separator(self, format):
        """Find out a char most suitable as dupe_separator"""

        self.options.dupe_separator = " "
        format_fname = os.path.basename(format)

        for x in ("%.t", "%s.n", "%s.N"):
            if format_fname.find(x) > -1:
                self.options.dupe_separator = "."
                return

        for x in ("%_t", "%s_n", "%s_N"):
            if format_fname.find(x) > -1:
                self.options.dupe_separator = "_"
                return

    def construct_path(self, filename):
        """Parses the filename and generates new name for renaming"""

        if self.options.verbose:
            loginf("filename: %s" % filename)

        guess = self.guess_info(filename)
        type = guess.get("vtype")
        mapping = []
        self.add_common_mapping(filename, guess, mapping)

        if type == "movie":
            dest_dir = self.options.movies_dir
            format = self.options.movies_format
            self.add_movies_mapping(guess, mapping)
        elif type == "series":
            dest_dir = self.options.series_dir
            format = self.options.series_format
            self.add_series_mapping(guess, mapping)
        elif type == "dated":
            dest_dir = self.options.dated_dir
            format = self.options.dated_format
            self.add_dated_mapping(guess, mapping)
        elif type == "othertv":
            dest_dir = self.options.othertv_dir
            format = self.options.othertv_format
            self.add_movies_mapping(guess, mapping)
        else:
            if self.options.verbose:
                loginf("Could not determine video type for %s" % filename)
            return None

        if dest_dir == "":
            dest_dir = os.path.dirname(self.options.download_dir)

        # Find out a char most suitable as dupe_separator
        self.guess_dupe_separator(format)

        # Add extension specifier if the format string doesn't end with it
        if format.rstrip("}")[-5:].lower() != ".%ext":
            format += ".%ext"

        sorter = format.replace("\\", "/")

        if self.options.verbose:
            loginf("format: %s" % sorter)

        # Replace elements
        path = Determine.path_subst(sorter, mapping)

        if self.options.verbose:
            loginf("path after subst: %s" % path)

        # Cleanup file name
        old_path = ""
        while old_path != path:
            old_path = path
            for key, name in Determine._REPLACE_AFTER.items():
                path = path.replace(key, name)

        # Uppercase all characters encased in {{}}
        path = Determine.to_uppercase(path)

        # Lowercase all characters encased in {}
        path = Determine.to_lowercase(path)

        # Strip any extra strippable characters around foldernames and filename
        path, ext = os.path.splitext(path)
        path = Determine.strip_folders(path)
        path = path + ext

        path = path.replace("%up", "..")

        path = os.path.normpath(path)
        dest_dir = os.path.normpath(dest_dir)

        if self.options.verbose:
            loginf("path after cleanup: %s" % path)

        new_path = os.path.normpath(os.path.join(dest_dir, *path.split(os.sep)))

        if self.options.verbose:
            loginf("destination path: %s" % new_path)

        if filename.upper() == new_path.upper():
            if self.options.verbose:
                loginf(f'construct_path: "{filename}" == "{new_path}": return None')
            return None

        if self.options.verbose:
            loginf(f'construct_path: "{filename}" --> "{new_path}"')
        return new_path


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
