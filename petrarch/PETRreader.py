# PETRreader.py [module]
##
# Dictionary and text input routines for the PETRARCH event coder
##
# CODE REPOSITORY: https://github.com/eventdata/PETRARCH
##
# SYSTEM REQUIREMENTS
# This program has been successfully run under Mac OS 10.10; it is standard
# Python 2.7 so it should also run in Unix or Windows.
#
# INITIAL PROVENANCE:
# Programmer: Philip A. Schrodt
#             Parus Analytics
#             Charlottesville, VA, 22901 U.S.A.
#             http://eventdata.parusanalytics.com
#
# GitHub repository: https://github.com/openeventdata/petrarch
#
# Copyright (c) 2014	Philip A. Schrodt.	All rights reserved.
#
# This project is part of the Open Event Data Alliance tool set; earlier
# developments were funded in part by National Science Foundation grant
# SES-1259190
#
# This code is covered under the MIT license
#
# Report bugs to: schrodt735@gmail.com
#
# REVISION HISTORY:
# 22-Nov-13:	Initial version
# Summer-14:	Numerous modifications to handle synonyms in actor and verb
#               dictionaries
# 20-Nov-14:	write_actor_root/text added to parse_Config
# ------------------------------------------------------------------------

from __future__ import print_function
from __future__ import unicode_literals

import io
import re
import os
import sys
import math  # required for ordinal date calculations
import logging
import xml.etree.ElementTree as ET

try:
    from ConfigParser import ConfigParser
except ImportError:
    from configparser import ConfigParser

import PETRglobals
import utilities
"""
CONVERTING TABARI DICTIONARIES TO PETRARCH FORMAT

1. The ';' comment delimiter no longer works: replace it with '#"

2. Lines beginning with '#' and '<' are considered comments and are skipped.
   If using '<', make this a one-line XML comment: <!-- ... -->.
   [The system currently doesn't recognize multi-line XML comments but this may
   change in the future.]

3. Final underscores are no longer needed since PETR does not do stemming.

"""

# ================== STRINGS ================== #

ErrMsgMissingDate = "<Sentence> missing required date; record was skipped"

# ================== EXCEPTIONS ================== #


class DateError(Exception):  # invalid date
    pass

# ================== CONFIG FILE INPUT ================== #


def parse_Config(config_path):
    """
    Parse PETRglobals.ConfigFileName. The file should be ; the default is
    PETR_config.ini in the working directory but this can be changed using the
    -c option in the command line. Most of the entries are obvious (but will
    eventually be documented) with the exception of

    1. actorfile_list and textfile_list are comma-delimited lists. Per the usual
    rules for Python config files, these can be continued on the next line
    provided the the first char is a space or tab.

    2. If both textfile_list and textfile_name are present, textfile_list takes
    priority.  textfile_list should be the name of a file containing text file
    names; # is allowed as a comment delimiter at the beginning of individual
    lines and following the file name.

    3. For additional info on config files, see
    http://docs.python.org/3.4/library/configparser.html or try Google, but
    basically, it is fairly simple, and you can probably just follow the
    examples.
    """

    def get_config_boolean(optname):
        """ Checks for the option optname, prints outcome and returns the result.
        If optname not present, returns False """
        if parser.has_option('Options', optname):
            try:
                result = parser.getboolean('Options', optname)
                print(optname, "=", result)
                return result
            except ValueError:
                print("Error in config.ini: " + optname +
                      " value must be `true' or `false'")
                raise
        else:
            return False

    print('\n', end=' ')
    parser = ConfigParser()
    # logger.info('Found a config file in working directory')
    confdat = parser.read(config_path)
    if len(confdat) == 0:
        print("\aError: Could not find the config file:",
              PETRglobals.ConfigFileName)
        print("Terminating program")
        sys.exit()

    try:
        PETRglobals.VerbFileName = parser.get('Dictionaries', 'verbfile_name')
        PETRglobals.AgentFileName = parser.get(
            'Dictionaries', 'agentfile_name')
        PETRglobals.DiscardFileName = parser.get('Dictionaries',
                                                 'discardfile_name')

        direct = parser.get('StanfordNLP', 'stanford_dir')
        PETRglobals.stanfordnlp = os.path.expanduser(direct)

        filestring = parser.get('Dictionaries', 'actorfile_list')
        PETRglobals.ActorFileList = filestring.split(', ')

        # otherwise this was set in command line
        if len(PETRglobals.TextFileList) == 0:
            if parser.has_option('Options', 'textfile_list'):  # takes priority
                filestring = parser.get('Options', 'textfile_list')
                PETRglobals.TextFileList = filestring.split(', ')
            else:
                filename = parser.get('Options', 'textfile_name')
                try:
                    fpar = open(filename, 'r')
                except IOError:
                    print("\aError: Could not find the text file list file:",
                          filename)
                    print("Terminating program")
                    sys.exit()
                PETRglobals.TextFileList = []
                line = fpar.readline()
                while len(line) > 0:  # go through the entire file
                    if '#' in line:
                        line = line[:line.find('#')]
                    line = line.strip()
                    if len(line) > 0:
                        PETRglobals.TextFileList.append(line)
                    line = fpar.readline()
                fpar.close()

        if parser.has_option('Dictionaries', 'issuefile_name'):
            PETRglobals.IssueFileName = parser.get('Dictionaries',
                                                   'issuefile_name')

        if parser.has_option('Options', 'new_actor_length'):
            try:
                PETRglobals.NewActorLength = parser.getint('Options',
                                                           'new_actor_length')
            except ValueError:
                print("Error in config.ini Option: "
                      "new_actor_length value must be an integer")
                raise
        print("new_actor_length =", PETRglobals.NewActorLength)

        PETRglobals.StoponError = get_config_boolean('stop_on_error')
        PETRglobals.WriteActorRoot = get_config_boolean('write_actor_root')
        PETRglobals.WriteActorText = get_config_boolean('write_actor_text')

        if parser.has_option('Options',
                             'require_dyad'):  # this one defaults to True
            PETRglobals.RequireDyad = get_config_boolean('require_dyad')
        else:
            PETRglobals.RequireDyad = True

        # otherwise this was set in command line
        if len(PETRglobals.EventFileName) == 0:
            PETRglobals.EventFileName = parser.get('Options', 'eventfile_name')

        PETRglobals.CodeBySentence = parser.has_option('Options',
                                                       'code_by_sentence')
        print("code-by-sentence", PETRglobals.CodeBySentence)

        PETRglobals.PauseBySentence = parser.has_option('Options',
                                                        'pause_by_sentence')
        print("pause_by_sentence", PETRglobals.PauseBySentence)

        PETRglobals.PauseByStory = parser.has_option('Options',
                                                     'pause_by_story')
        print("pause_by_story", PETRglobals.PauseByStory)

        try:
            if parser.has_option('Options', 'comma_min'):
                PETRglobals.CommaMin = parser.getint('Options', 'comma_min')
            elif parser.has_option('Options', 'comma_max'):
                PETRglobals.CommaMax = parser.getint('Options', 'comma_max')
            elif parser.has_option('Options', 'comma_bmin'):
                PETRglobals.CommaBMin = parser.getint('Options', 'comma_bmin')
            elif parser.has_option('Options', 'comma_bmax'):
                PETRglobals.CommaBMax = parser.getint('Options', 'comma_bmax')
            elif parser.has_option('Options', 'comma_emin'):
                PETRglobals.CommaEMin = parser.getint('Options', 'comma_emin')
            elif parser.has_option('Options', 'comma_emax'):
                PETRglobals.CommaEMax = parser.getint('Options', 'comma_emax')
        except ValueError:
            print(
                "Error in config.ini Option: comma_*  value must be an integer")
            raise
        print("Comma-delimited clause elimination:")
        print("Initial :", end=' ')
        if PETRglobals.CommaBMax == 0:
            print("deactivated")
        else:
            print("min =", PETRglobals.CommaBMin, "   max =",
                  PETRglobals.CommaBMax)
        print("Internal:", end=' ')
        if PETRglobals.CommaMax == 0:
            print("deactivated")
        else:
            print("min =", PETRglobals.CommaMin, "   max =",
                  PETRglobals.CommaMax)
        print("Terminal:", end=' ')
        if PETRglobals.CommaEMax == 0:
            print("deactivated")
        else:
            print("min =", PETRglobals.CommaEMin, "   max =",
                  PETRglobals.CommaEMax)

    except Exception as e:
        print('parse_config() encountered an error: check the options in',
              PETRglobals.ConfigFileName)
        print("Terminating program")
        sys.exit()
#    logger.warning('Problem parsing config file. {}'.format(e))

# ================== PRIMARY INPUT USING FIN ================== #


def open_FIN(filename, descrstr):
    # opens the global input stream fin using filename;
    # descrstr provides information about the file in the event it isn't found
    global FIN
    global FINline, FINnline, CurrentFINname
    try:
        FIN = io.open(filename, 'r', encoding='utf-8')
        CurrentFINname = filename
        FINnline = 0
    except IOError:
        print("\aError: Could not find the", descrstr, "file:", filename)
        print("Terminating program")
        sys.exit()


def close_FIN():
    # closes the global input stream fin.
    # IOError should only happen during debugging or if something has seriously
    # gone wrong
    # with the system, so exit if this occurs.
    global FIN
    try:
        FIN.close()
    except IOError:
        print("\aError: Could not close the input file")
        print("Terminating program")
        sys.exit()


def read_FIN_line():
    """
    def read_FIN_line():
    Reads a line from the input stream fin, deleting xml comments and lines
    beginning with # returns next non-empty line or EOF
    tracks the current line number (FINnline) and content (FINline)
    calling function needs to handle EOF (len(line) == 0)

    For legacy purposes, the perl/Python one-line comment delimiter # the
    beginning of a line is also recognized. Blank lines and lines with only
    whitespace are also skipped.
    """

    global FIN
    global FINline, FINnline

    line = FIN.readline()
    FINnline += 1
    while True:
        if len(line) == 0:
            break  # calling function needs to handle EOF
        # deal with simple lines we need to skip
        if line[0] == '#' or line[0] == '\n' or line[0:2] == '<!' or len(
                line.strip()) == 0:
            line = FIN.readline()
            FINnline += 1
            continue
        if not line:  # handle EOF
            print("EOF hit in read_FIN_line()")
            raise EOFError
            return line
        if (' #' in line):
            line = line[:line.rfind(' #')]

        if ('<!--' in line):
            if ('-->' in line):  # just remove the substring
                pline = line.partition('<!--')
                line = pline[0] + pline[2][pline[2].find('-->') + 3:]
            else:
                while ('-->' not in line):
                    line = FIN.readline()
                    FINnline += 1
                line = FIN.readline()
                FINnline += 1
        if len(line.strip()) > 0:
            break
        line = FIN.readline()
        FINnline += 1
    FINline = line
    return line

# ========================= TAG EVALUATION FUNCTIONS ======================== #


def find_tag(tagstr):
    # reads fin until tagstr is found
    # can inherit EOFError raised in PETRreader.read_FIN_line()
    line = read_FIN_line()
    while (tagstr not in line):
        line = read_FIN_line()


def extract_attributes(theline):
    # puts list of attribute and content pairs in the global AttributeList.
    # First item is the tag itself. If a twice-double-quote occurs -- "" -- this
    # treated as "\" still to do: need error checking here
    """
    Structure of attributes extracted to AttributeList At present, these always
    require a quoted field which follows an '=', though it probably makes sense
    to make that optional and allow attributes without content
    """

    theline = theline.strip()
    if ' ' not in theline:  # theline only contains a keyword
        PETRglobals.AttributeList = theline[1:-2]
        return

    pline = theline[1:].partition(' ')  # skip '<'
    PETRglobals.AttributeList = [pline[0]]
    theline = pline[2]
    while ('=' in theline):  # get the field and content pairs
        pline = theline.partition('=')
        PETRglobals.AttributeList.append(pline[0].strip())
        theline = pline[2]
        pline = theline.partition('"')
        if pline[2][0] == '"':  # twice-double-quote
            pline = pline[2][1:].partition('"')
            PETRglobals.AttributeList.append('"' + pline[0] + '"')
            theline = pline[2][1:]
        else:
            pline = pline[2].partition('"')
            PETRglobals.AttributeList.append(pline[0].strip())
            theline = pline[2]


def check_attribute(targattr):
    """
    Looks for targetattr in AttributeList; returns value if found, null string
    otherwise.
    """
    # This is used if the attribute is optional (or if error checking is handled
    # by the calling routine); if an error needs to be raised, use
    # get_attribute()
    if (targattr in PETRglobals.AttributeList):
        return (
            PETRglobals.AttributeList[PETRglobals.AttributeList.index(targattr)
                                      + 1])
    else:
        return ""


def get_attribute(targattr):
    """
    Similar to check_attribute() except it raises a MissingAttr error when the
    attribute is missing.
    """
    if (targattr in PETRglobals.AttributeList):
        return (
            PETRglobals.AttributeList[PETRglobals.AttributeList.index(targattr)
                                      + 1])
    else:
        raise MissingAttr
        return ""

# ================== ANCILLARY DICTIONARY INPUT ================== #


def read_discard_list(discard_path):
    """
    Reads file containing the discard list: these are simply lines containing
    strings.  If the string, prefixed with ' ', is found in the <Text>...</Text>
    sentence, the sentence is not coded. Prefixing the string with a '+' means
    the entire story is not coded with the string is found [see read_record()
    for details on story/sentence identification]. If the string ends with '_',
    the matched string must also end with a blank or punctuation mark; otherwise
    it is treated as a stem. The matching is not case sensitive.

    The file format allows # to be used as a in-line comment delimiter.

    File is stored as a simple list and the interpretation of the strings is
    done in check_discards()
    """

    logger = logging.getLogger('petr_log')
    logger.info("Reading " + PETRglobals.DiscardFileName)
    open_FIN(discard_path, "discard")

    line = read_FIN_line()
    while len(line) > 0:  # loop through the file
        if '#' in line:
            line = line[:line.find('#')]
        targ = line.strip()
        if targ.startswith('+'):
            targ = '+ ' + targ[1:]
        else:
            targ = ' ' + targ
        PETRglobals.DiscardList.append(targ.upper())  # case insensitive match
        line = read_FIN_line()
    close_FIN()


def read_issue_list(issue_path):
    """
    "Issues" do simple string matching and return a comma-delimited list of
    codes.  The standard format is simply
            <string> [<code>]
    For purposes of matching, a ' ' is added to the beginning and end of the
    string: at present there are not wild cards, though that is easily added.

    The following expansions can be used (these apply to the string that follows
    up to the next blank)
            n: Create the singular and plural of the noun
            v: Create the regular verb forms ('S','ED','ING')
            +: Create versions with ' ' and '-'

    The file format allows # to be used as a in-line comment delimiter.

    File is stored in PETRglobals.IssueList as a list of tuples (string, index)
    where index refers to the location of the code in PETRglobals.IssueCodes.
    The coding is done in check_issues()

    Issues are written to the event record as a comma-delimited list to a
    tab-delimited field.

    This feature is optional and triggered by a file name in the PETR_config.ini
    file at: issuefile_name = Phoenix.issues.140225.txt

    <14.02.28> NOT YET FULLY IMPLEMENTED
    The prefixes '~' and '~~' indicate exclusion phrases:
            ~ : if the string is found in the current sentence, do not code any
                of the issues in section -- delimited by <ISSUE
                CATEGORY="...">...</ISSUE> -- containing the string
            ~~ : if the string is found in the current *story*, do not code any
                of the issues in section
    In the current code, the occurrence of an ignore phrase of either type
    cancels all coding of issues from the sentence
    """

    logger = logging.getLogger('petr_log')
    logger.info("Reading " + PETRglobals.IssueFileName)
    open_FIN(issue_path, "issues")

    PETRglobals.IssueCodes.append('~')  # initialize the ignore codes
    PETRglobals.IssueCodes.append('~~')

    line = read_FIN_line()
    while len(line) > 0:  # loop through the file
        if '#' in line:
            line = line[:line.find('#')]
        if line[0] == '~':  # ignore codes are only partially implemented
            if line[1] == '~':
                target = line[2:].strip().upper()
                codeindex = 1
            else:
                target = line[1:].strip().upper()
                codeindex = 0
        else:
            if '[' not in line:  # just do the codes now
                line = read_FIN_line()
                continue
            code = line[line.find('[') + 1:line.find(']')]  # get the code
            if code in PETRglobals.IssueCodes:
                codeindex = PETRglobals.IssueCodes.index(code)
            else:
                PETRglobals.IssueCodes.append(code)
                codeindex = len(PETRglobals.IssueCodes) - 1
            target = line[:line.find('[')].strip().upper()

        forms = [target]
        madechange = True
        while madechange:  # iterate until no more changes to make
            ka = 0
            madechange = False
            while ka < len(forms):
                if '+' in forms[ka]:
                    str = forms[ka]
                    forms[ka] = str.replace('+', ' ', 1)
                    forms.insert(ka + 1, str.replace('+', '-', 1))
                    madechange = True
                if 'N:' in forms[ka]:  # regular noun forms
                    part = forms[ka].partition('N:')
                    forms[ka] = part[0] + part[2]
                    plur = part[2].partition(' ')
                    if 'Y' == plur[0][-1]:
                        plural = plur[0][:-1] + 'IES'
                    else:
                        plural = plur[0] + 'S'
                    forms.insert(ka + 1, part[0] + plural + ' ' + plur[2])
                    madechange = True
                if 'V:' in forms[ka]:  # regular verb forms
                    part = forms[ka].partition('V:')
                    forms[ka] = part[0] + part[2]
                    root = part[2].partition(' ')
                    vscr = root[0] + "S"
                    forms.insert(ka + 1, part[0] + vscr + ' ' + root[2])
                    if root[0][-1] == 'E':  # root ends in 'E'
                        vscr = root[0] + "D "
                        forms.insert(ka + 2, part[0] + vscr + ' ' + root[2])
                        vscr = root[0][:-1] + "ING "
                    else:
                        vscr = root[0] + "ED "
                        forms.insert(ka + 2, part[0] + vscr + ' ' + root[2])
                        vscr = root[0] + "ING "
                    forms.insert(ka + 3, part[0] + vscr + ' ' + root[2])
                    madechange = True

                ka += 1

        for item in forms:
            PETRglobals.IssueList.append(tuple([' ' + item + ' ', codeindex]))
        line = read_FIN_line()
    close_FIN()

# ================== VERB DICTIONARY INPUT ================== #


def read_verb_dictionary(verb_path):
    """
    Reads the verb dictionary from VerbFileName
    """

    global theverb, verb  # <14.05.07> : not needed, right?

    def make_phrase_list(thepat):
        """
        Converts a pattern phrase into a list of alternating words and
        connectors
        """
        if len(thepat) == 0:
            return []
        phlist = []
        start = 0
        maxlen = len(thepat) + 1  # this is just a telltail
        while start < len(thepat):  # break phrase on ' ' and '_'
            spfind = thepat.find(' ', start)
            if spfind == -1:
                spfind = maxlen
            unfind = thepat.find('_', start)
            if unfind == -1:
                unfind = maxlen
            # somehow think I don't need this check...well, I just need the
            # terminating point, still need to see which is lower
            if unfind < spfind:
                phlist.append(thepat[start:unfind])
                phlist.append('_')
                start = unfind + 1
            else:
                phlist.append(thepat[start:spfind])
                phlist.append(' ')
                start = spfind + 1
                # check for missing synsets
        ka = 0
        while ka < len(phlist):
            if len(phlist[ka]) > 0:
                if (phlist[ka][0] == '&') and (
                        phlist[ka] not in PETRglobals.VerbDict):
                    logger.warning("Synset " + phlist[ka] +
                                   " has not been defined; pattern skipped")
                    raise ValueError  # this will do...
            ka += 2
        return phlist

    def get_verb_forms(loccode):
        """
        Read the irregular forms of a verb.
        """
        # need error checking here
        global verb, theverb
        forms = verb[verb.find('{') + 1:verb.find('}')].split()

        for wrd in forms:
            vscr = wrd + " "
            PETRglobals.VerbDict[vscr] = [False, loccode, theverb]

    def store_multi_word_verb(loccode):
        """
        Store a multi-word verb and optional irregular forms.  Multi-words are
        stored in a list consisting of code primary form (use as a pointer to
        the pattern tuple: (True if verb is at start of list, False otherwise;
        remaining words)
        """

        global verb, theverb

        if '{' in verb:
            forms = verb[verb.find('{') + 1:verb.find('}')].split()
            forms.append(verb[:verb.find('{')].strip())
        else:
            forms = [verb]
        for phrase in forms:
            if '+' in phrase:  # otherwise not in correct form so skip it
                words = phrase.split('_')
                if words[0].startswith('+'):
                    multilist = [True]
                    for ka in range(1, len(words)):
                        multilist.append(words[ka])
                    targverb = words[0][1:] + ' '
                else:
                    multilist = [False]
                    for ka in range(2, len(words) + 1):
                        multilist.append(words[len(words) - ka])
                    targverb = words[len(words) - 1][1:] + ' '

                if targverb in PETRglobals.VerbDict:
                    PETRglobals.VerbDict[targverb].insert(2, [loccode, theverb,
                                                              tuple(multilist)])
                else:
                    PETRglobals.VerbDict[targverb] = [True, '---',
                                                      [loccode, theverb,
                                                       tuple(multilist)]]

    def make_verb_forms(loccode):
        """
        Create the regular forms of a verb.
        """

        global verb, theverb
        vroot = verb[:-1]
        vscr = vroot + "S "
        PETRglobals.VerbDict[vscr] = [False, loccode, theverb]
        if vroot[-1] == 'E':  # root ends in 'E'
            vscr = vroot + "D "
            PETRglobals.VerbDict[vscr] = [False, loccode, theverb]
            vscr = vroot[:-1] + "ING "
        else:
            vscr = vroot + "ED "
            PETRglobals.VerbDict[vscr] = [False, loccode, theverb]
            vscr = vroot + "ING "
        PETRglobals.VerbDict[vscr] = [False, loccode, theverb]

    def make_plural(st):
        """
        Create the plural of a synonym noun st
        """

        if 'Y' == st[-1]:
            return st[:-1] + 'IES'  # space is added below
        elif 'S' == st[-1]:
            return st[:-1] + 'ES'
        else:
            return st + 'S'

    # note that this will be ignored if there are no errors
    logger = logging.getLogger('petr_log')
    logger.info("Reading " + PETRglobals.VerbFileName)
    open_FIN(verb_path, "verb")

    theverb = ''
    newblock = False
    ka = 0  # primary verb count ( debug )
    line = read_FIN_line()
    while len(line) > 0:  # loop through the file
        if '[' in line:
            part = line.partition('[')
            verb = part[0].strip() + ' '
            code = part[2][:part[2].find(']')]
        else:
            verb = line.strip() + ' '
            code = ''

        if verb.startswith('---'):  # start of new block
            if len(code) > 0:
                primarycode = code
            else:
                primarycode = '---'
            newblock = True
            line = read_FIN_line()

        elif verb[0] == '-':  # pattern
            # TABARI legacy: currently aren't processing these
            if '{' in verb:
                line = read_FIN_line()
                continue
# resolve the ambiguous '_ ' construction to ' '
            verb = verb.replace('_ ', ' ')
            targ = verb[1:].partition('*')
            try:
                highpat = make_phrase_list(targ[0].lstrip())
                highpat.reverse()
                lowphrase = targ[2].rstrip()
                if len(lowphrase) == 0:
                    lowpat = []
                else:
                    lowpat = [targ[2][0]]  # start with connector
                    loclist = make_phrase_list(lowphrase[1:])
                    lowpat.extend(loclist[:-1])  # don't need the final blank
                PETRglobals.VerbDict[theverb].append([highpat, lowpat, code])
            except ValueError:
                # just trap the error, which will skip the line containing it
                pass
            line = read_FIN_line()

        elif verb[0] == '&':  # Read and store a synset.
            if verb[-2] == '_':
                noplural = True
                verb = verb[:-2]  # remove final blank and _
            else:
                noplural = False
                verb = verb[:-1]  # remove final blank
            PETRglobals.VerbDict[verb] = []
            line = read_FIN_line()
            while line[0] == '+':
                wordstr = line[1:].strip()
                if noplural or wordstr[-1] == '_':
                    # get rid of internal _ since the strings themselves will
                    # handle consecutive matches
                    wordstr = wordstr.strip().replace('_', ' ')
                    # <14.05.08> Multi-word phrases are always converted to
                    # lists between checking, so probably it would be useful to
                    # store them as tuples once this has stabilized
                    PETRglobals.VerbDict[verb].append(wordstr)
                else:
                    wordstr = wordstr.replace('_', ' ')
                    PETRglobals.VerbDict[verb].append(wordstr)
                    PETRglobals.VerbDict[verb].append(make_plural(wordstr))
                line = read_FIN_line()

        else:  # verb
            # if theverb != '': print '::', theverb,
            # PETRglobals.VerbDict[theverb]
            if len(code) > 0:
                curcode = code
            else:
                curcode = primarycode
            if newblock:
                if '{' in verb:
                    # theverb is the index to the pattern storage for the
                    # remainder of the block
                    theverb = verb[:verb.find('{')].strip() + ' '
                else:
                    theverb = verb
                PETRglobals.VerbDict[theverb] = [True, curcode]
                newblock = False
            if '_' in verb:
                store_multi_word_verb(curcode)
            else:
                if '{' in verb:
                    get_verb_forms(curcode)
                else:
                    make_verb_forms(curcode)
            ka += 1  # counting primary verbs
            #           if ka > 16: return
            line = read_FIN_line()

    close_FIN()


def show_verb_dictionary(filename=''):
    # debugging function: displays VerbDict to screen or writes to filename
    if len(filename) > 0:
        fout = open(filename, 'w')
        fout.write('PETRARCH Verb Dictionary Internal Format\n')
        fout.write('Run time: ' + PETRglobals.RunTimeString + '\n')

        for locword, loclist in PETRglobals.VerbDict.items():
            if locword[0] == '&':
                continue
            fout.write(locword)
            if loclist[0]:
                if len(loclist) > 1:
                    # pattern list
                    fout.write("::\n" + str(loclist[1:]) + "\n")
                else:
                    fout.write(":: " + str(loclist[1]) + "\n")  # simple code
            else:
                # pointer
                fout.write('-> ' + str(loclist[2]) + ' [' + loclist[1] + ']\n')
        fout.close()

    else:
        for locword, loclist in PETRglobals.VerbDict.items():
            print(locword, end=' ')
            if loclist[0]:
                if len(loclist) > 2:
                    print('::\n', loclist[1:])  # pattern list
                else:
                    print(':: ', loclist[1])  # simple code
            else:
                print('-> ', loclist[2], '[' + loclist[1] + ']')

# ================== ACTOR DICTIONARY INPUT ================== #


def make_noun_list(nounst):
    # parses a noun string -- actor, agent or agent plural -- and returns in a
    # list which has the keyword and initial connector in the first tuple
    nounlist = []
    start = 0
    maxlen = len(nounst) + 1  # this is just a telltail
    while start < len(nounst):  # break phrase on ' ' and '_'
        spfind = nounst.find(' ', start)
        if spfind == -1:
            spfind = maxlen
        unfind = nounst.find('_', start)
        if unfind == -1:
            unfind = maxlen
        # <13.06.05> not sure we need this check...well, I just need the
        # terminating point, still need to see which is lower
        if unfind < spfind:
            # this won't change, so use a tuple
            nounlist.append((nounst[start:unfind], '_'))
            start = unfind + 1
        else:
            nounlist.append((nounst[start:spfind], ' '))
            start = spfind + 1
    return nounlist


def dstr_to_ordate(datestring):
    """
    Computes an ordinal date from a Gregorian calendar date string YYYYMMDD or
    YYMMDD.

    This uses the 'ANSI date' with the base -- ordate == 1 -- of 1 Jan 1601.
    This derives from [OMG!] COBOL (see http://en.wikipedia.org/wiki/Julian_day)
    but in fact should work fairly well for our applications.

    For consistency with KEDS and TABARI, YY years between 00 and 30 are
    interpreted as 20YY; otherwise 19YY is assumed.

    Formatting and error checking:
    1. YYMMDD dates *must* be <=7 characters, otherwise YYYYMMDD is assumed
    2. If YYYYMMDD format is used, only the first 8 characters are checked so it
        is okay to have junk at the end of the string.
    3. Days are checked for validity according to the month and year, e.g.
        20100931 is never allowed; 20100229 is not valid but 20120229 is valid
    4. Invalid dates raise DateError

    Source of algorithm: http://en.wikipedia.org/wiki/Julian_day

    Unit testing:
    Julian dates from http://aa.usno.navy.mil/data/docs/JulianDate.php (set time
    to noon)
    Results:
        dstr_to_ordate("20130926") # 2456562
        dstr_to_ordate("090120") # 2454852
        dstr_to_ordate("510724")  # 2433852
        dstr_to_ordate("19411207")  # 2430336
        dstr_to_ordate("18631119")  # 2401829
        dstr_to_ordate("17760704")  # 2369916
        dstr_to_ordate("16010101")  # 2305814
    """

    try:
        if len(datestring) > 7:
            year = int(datestring[:4])
            month = int(datestring[4:6])
            day = int(datestring[6:8])
        else:
            year = int(datestring[:2])
            if year <= 30:
                year += 2000
            else:
                year += 1900
            month = int(datestring[2:4])
            day = int(datestring[4:6])
    except ValueError:
        raise DateError

    if day <= 0:
        raise DateError

    if month == 2:
        if year % 400 == 0:
            if day > 29:
                raise DateError
        elif year % 100 == 0:
            if day > 28:
                raise DateError
        elif year % 4 == 0:
            if day > 29:
                raise DateError
        else:
            if day > 28:
                raise DateError
    elif month in [4, 6, 9, 11]:
        if day > 30:
            raise DateError
    else:
        if day > 31:
            raise DateError

    if (month < 3):
        adj = 1
    else:
        adj = 0
    yr = year + 4800 - adj
    mo = month + (12 * adj) - 3
    ordate = day + math.floor((153 * mo + 2) / 5) + 365 * yr
    ordate += math.floor(yr / 4) - math.floor(yr / 100) + math.floor(
        yr / 400) - 32045  # pure Julian date
    # print "Julian:", ordate        # debug to cross-check for unit test
    ordate -= 2305813  # adjust for ANSI date

    # print ordate        # debug
    return int(ordate)


def read_actor_dictionary(actorfile):
    """ Reads a TABARI-style actor dictionary.
    Actor dictionary list elements: Actors are stored in a dictionary of a list
    of pattern lists keyed on the first word of the phrase. The pattern lists
    are sorted by length.  The individual pattern lists begin with an integer
    index to the tuple of possible codes (that is, with the possibility of date
    restrictions) in PETRglobals.ActorCodes, followed by the connector from the
    key, and then a series of 2-tuples containing the remaining words and
    connectors. A 2-tuple of the form ('', ' ') signals the end of the list.
    <14.02.26: Except at the moment these are just 2-item lists, not tuples, but
    this could be easily changed and presumably would be more efficient: these
    are not changed so they don't need to be lists.<>
    """

    dateerrorstr = ("String in date restriction could not be interpreted; "
                    "line skipped")

    logger = logging.getLogger('petr_log')
    logger.info("Reading " + actorfile)
    open_FIN(actorfile, "actor")

    # location where codes for current actor will be stored
    codeindex = len(PETRglobals.ActorCodes)
    # list of codes -- default and date restricted -- for current actor
    curlist = []

    line = read_FIN_line()
    while len(line) > 0:  # loop through the file
        if '---STOP---' in line:
            break
        if line[0] == '\t':  # deal with date restriction
            try:
                brack = line.index('[')
            except ValueError:
                logger.warning(dateerrorstr)
                line = read_FIN_line()
                continue
            part = line[brack + 1:].strip().partition(' ')
            code = part[0].strip()
            rest = part[2].lstrip()
            if '<' in rest or '>' in rest:
                # find an all-digit string: this is more robust than the TABARI
                # equivalent
                ka = 1
                while (ka < len(rest)) and (not rest[ka].isdigit()):
                    # if this fails the length test, it will be caught as
                    # DateError
                    ka += 1
                kb = ka + 6
                while (kb < len(rest)) and (rest[kb].isdigit()):
                    kb += 1
                try:
                    ord = dstr_to_ordate(rest[ka:kb])
                except DateError:
                    logger.warning(dateerrorstr)
                    line = read_FIN_line()
                    continue

                if rest[0] == '<':
                    curlist.append([0, ord, code])
                else:
                    curlist.append([1, ord, code])
            elif '-' in rest:
                part = rest.partition('-')
                try:
                    pt0 = part[0].strip()
                    ord1 = dstr_to_ordate(pt0)
                    part2 = part[2].partition(']')
                    pt2 = part2[0].strip()
                    ord2 = dstr_to_ordate(pt2)
                except DateError:
                    logger.warning(dateerrorstr)
                    line = read_FIN_line()
                    continue
                if ord2 < ord1:
                    logger.warning("End date in interval date restriction is "
                                   "less than starting date; line skipped")
                    line = read_FIN_line()
                    continue
                curlist.append([2, ord1, ord2, code])
            else:  # replace default code
                # list containing a single code
                curlist.append([code[:code.find(']')]])

        else:
            if line[0] == '+':  # deal with synonym
                part = line.partition(';')  # split on comment, if any
                actor = part[0][1:].strip() + ' '
            else:  # primary phrase with code
                if len(curlist) > 0:
                    if PETRglobals.WriteActorRoot:
                        curlist.append(rootactor)
                    PETRglobals.ActorCodes.append(
                        tuple(curlist)
                    )  # store code from previous entry
                    codeindex = len(PETRglobals.ActorCodes)
                    curlist = []
                if '[' in line:  # code specified?
                    part = line.partition('[')
                    # list containing a single code
                    curlist.append([part[2].partition(']')[0].strip()])
                else:
                    # no code, so don't update curlist
                    part = line.partition(';')
                actor = part[0].strip() + ' '
                rootactor = actor
            nounlist = make_noun_list(actor)
            keyword = nounlist[0][0]
            phlist = [codeindex, nounlist[0][1]] + nounlist[1:]
            # we don't need to store the first word, just the connector
            if keyword in PETRglobals.ActorDict:
                PETRglobals.ActorDict[keyword].append(phlist)
            else:
                PETRglobals.ActorDict[keyword] = [phlist]
            if isinstance(phlist[0], str):
                # save location of the list if this is a primary phrase
                curlist = PETRglobals.ActorDict[keyword]

        line = read_FIN_line()

    close_FIN()
    #    <14.11.20: does this need to save the final entry? >

    # sort the patterns by the number of words
    for lockey in list(PETRglobals.ActorDict.keys()):
        PETRglobals.ActorDict[lockey].sort(key=len, reverse=True)


def show_actor_dictionary(filename=''):
    # debugging function: displays ActorDict to screen or writes to filename
    if len(filename) > 0:
        fout = open(filename, 'w')
        fout.write(
            'PETRARCH Actor Dictionary and Actor Codes Internal Format\n')
        fout.write('Run time: ' + PETRglobals.RunTimeString + '\n')

        for locword, loclist in PETRglobals.ActorDict.items():
            fout.write(locword + " ::\n" + str(loclist) + "\n")

        fout.write('\nActor Codes\n')
        ka = 0
        while ka < len(PETRglobals.ActorCodes):
            fout.write(str(ka) + ': ' + str(PETRglobals.ActorCodes[ka]) + '\n')
            ka += 1

        fout.close()

    else:
        for locword, loclist in PETRglobals.ActorDict.items():
            print(locword, "::")
            if isinstance(loclist[0][0], str):
                print(loclist)  # debug
            else:
                print('PTR,', loclist)


# ================== AGENT DICTIONARY INPUT ================== #
def read_agent_dictionary(agent_path):
    """ Reads an agent dictionary
    Agents are stored in a simpler version of the Actors dictionary: a list of
    phrases keyed on the first word of the phrase.  The individual phrase lists
    begin with the code, the connector from the key, and then a series of
    2-tuples containing the remaining words and connectors. A 2-tuple of the
    form ('', ' ') signals the end of the list.

    Connector:
            blank: words can occur between the previous word and the next word
            _ (underscore): words must be consecutive: no intervening words
    """
    global subdict

    def store_agent(nounst, code):
        # parses nounstring and stores the result with code
        nounlist = make_noun_list(nounst)
        keyword = nounlist[0][0]
        phlist = [code, nounlist[0][1]] + nounlist[1:]
        # we don't need to store the first word, just the connector
        if keyword in PETRglobals.AgentDict:
            PETRglobals.AgentDict[keyword].append(phlist)
        else:
            PETRglobals.AgentDict[keyword] = [phlist]
        # <13.12.16> : this isn't needed for agents, correct?
        if isinstance(phlist[0], str):
            # save location of the list if this is a primary phrase
            curlist = PETRglobals.AgentDict[keyword]

    def define_marker(line):
        global subdict
        if line[line.find('!') + 1:].find(
                '!') < 0 or line[line.find('!'):].find('=') < 0:
            logger.warning(markdeferrorstr + enderrorstr)
            return
        ka = line.find('!') + 1
        marker = line[ka:line.find('!', ka)]
        loclist = line[line.find('=', ka) + 1:].strip()
        subdict[marker] = []
        for item in loclist.split(','):
            subdict[marker].append(item.strip())

    def store_marker(agent, code):
        global subdict
        if agent[agent.find('!') + 1:].find('!') < 0:
            ka = agent.find('!')
            logger.warning("Substitution marker \"" + agent[ka:agent.find(
                ' ', ka) + 1] + "\" syntax incorrect" + enderrorstr)
            return
        part = agent.partition('!')
        part2 = part[2].partition('!')
        if part2[0] not in subdict:
            logger.warning("Substitution marker !" + part2[0] +
                           "! missing in .agents file; line skipped")
            return
        for subst in subdict[part2[0]]:
            # print part[0]+subst+part2[2]
            store_agent(part[0] + subst + part2[2], code)

    # this is just called when the program is loading, so keep them local.
    # <14.04.22> Or just put these as constants in the function calls: does it
    # make a difference?
    enderrorstr = " in .agents file ; line skipped"
    codeerrorstr = "Codes are required for agents"
    brackerrorstr = "Missing '}'"
    markdeferrorstr = "Substitution marker incorrectly defined"

    subdict = {}  # substitution set dictionary

    # note that this will be ignored if there are no errors
    logger = logging.getLogger('petr_log')
    logger.info("Reading " + PETRglobals.AgentFileName + "\n")
    open_FIN(agent_path, "agent")

    line = read_FIN_line()
    while len(line) > 0:  # loop through the file

        if '!' in line and '=' in line:  # synonym set
            define_marker(line)
            line = read_FIN_line()
            continue

        if '[' not in line:  # code specified?
            logger.warning(codeerrorstr + enderrorstr)
            line = read_FIN_line()
            continue

        part = line.partition('[')
        code = part[2].partition(']')[0].strip()
        agent = part[0].strip() + ' '
        if '!' in part[0]:
            store_marker(agent, code)  # handle a substitution marker
        elif '{' in part[0]:
            if '}' not in part[0]:
                logger.warning(brackerrorstr + enderrorstr)
                line = read_FIN_line()
                continue
            agent = part[0][:part[0].find('{')].strip() + ' '
            # this will automatically set the null case
            plural = part[0][part[0].find('{') + 1:part[0].find('}')].strip()
        else:
            if 'Y' == agent[-2]:
                plural = agent[:-2] + 'IES'  # space is added below
            elif 'S' == agent[-2]:
                plural = agent[:-1] + 'ES'
            else:
                plural = agent[:-1] + 'S'

        store_agent(agent, code)
        if len(plural) > 0:
            store_agent(plural + ' ', code)

        line = read_FIN_line()

    close_FIN()

    # sort the patterns by the number of words
    for lockey in list(PETRglobals.AgentDict.keys()):
        PETRglobals.AgentDict[lockey].sort(key=len, reverse=True)


def show_AgentDict(filename=''):
    # debugging function: displays AgentDict to screen or writes to filename
    if len(filename) > 0:
        fout = open(filename, 'w')
        fout.write('PETRARCH Agent Dictionary Internal Format\n')
        fout.write('Run time: ' + PETRglobals.RunTimeString + '\n')

        for locword, loclist in PETRglobals.AgentDict.items():
            fout.write(locword + " ::\n")
            fout.write(str(loclist) + "\n")
        fout.close()

    else:
        for locword, loclist in PETRglobals.AgentDict.items():
            print(locword, "::")
            print(loclist)

# ==== Input format reading


def read_xml_input(filepaths, parsed=False):
    """
    Reads input in the PETRARCH XML-input format and creates the global holding
    dictionary. Please consult the documentation for more information on the
    format of the global holding dictionary. The function iteratively parses
    each file so is capable of processing large inputs without failing.

    Parameters
    ----------

    filepaths: List.
                List of XML files to process.


    parsed: Boolean.
            Whether the input files contain parse trees as generated by
            StanfordNLP.

    Returns
    -------

    holding: Dictionary.
                Global holding dictionary with StoryIDs as keys and various
                sentence- and story-level attributes as the inner dictionaries.
                Please refer to the documentation for greater information on
                the format of this dictionary.
    """
    holding = {}

    for path in filepaths:
        tree = ET.iterparse(path)

        for event, elem in tree:
            if event == "end" and elem.tag == "Sentence":
                story = elem

                # Check to make sure all the proper XML attributes are included
                attribute_check = [
                    key in story.attrib
                    for key in ['date', 'id', 'sentence', 'source']
                ]
                if not attribute_check:
                    print('Need to properly format your XML...')
                    break

                # If the XML contains StanfordNLP parsed data, pull that out
                # TODO: what to do about parsed content at the story level,
                # i.e., multiple parsed sentences within the XML entry?
                if parsed:
                    parsed_content = story.find('Parse').text
                    parsed_content = utilities._format_parsed_str(
                        parsed_content)
                else:
                    parsed_content = ''

                # Get the sentence information
                if story.attrib['sentence'] == 'True':
                    entry_id, sent_id = story.attrib['id'].split('_')

                    text = story.find('Text').text
                    text = text.replace('\n', '').replace('  ', '')
                    sent_dict = {'content': text, 'parsed': parsed_content}
                    meta_content = {
                        'date': story.attrib['date'],
                        'source': story.attrib['source']
                    }
                    content_dict = {
                        'sents': {sent_id: sent_dict},
                        'meta': meta_content
                    }
                else:
                    entry_id = story.attrib['id']

                    text = story.find('Text').text
                    text = text.replace('\n', '').replace('  ', '')
                    split_sents = _sentence_segmenter(text)
                    # TODO Make the number of sents a setting
                    sent_dict = {}
                    for i, sent in enumerate(split_sents[:7]):
                        sent_dict[
                            i
                        ] = {'content': sent,
                             'parsed': parsed_content}

                    meta_content = {'date': story.attrib['date']}
                    content_dict = {'sents': sent_dict, 'meta': meta_content}

                if entry_id not in holding:
                    holding[entry_id] = content_dict
                else:
                    holding[entry_id]['sents'][sent_id] = sent_dict

                elem.clear()

    return holding


def read_pipeline_input(pipeline_list):
    """
    Reads input from the processing pipeline and MongoDB and creates the global
    holding dictionary. Please consult the documentation for more information
    on the format of the global holding dictionary. The function iteratively
    parses each file so is capable of processing large inputs without failing.

    Parameters
    ----------

    pipeline_list: List.
                    List of dictionaries as stored in the MongoDB instance.
                    These records are originally generated by the
                    `web scraper <https://github.com/openeventdata/scraper>`_.

    Returns
    -------

    holding: Dictionary.
                Global holding dictionary with StoryIDs as keys and various
                sentence- and story-level attributes as the inner dictionaries.
                Please refer to the documentation for greater information on
                the format of this dictionary.
    """
    holding = {}
    for entry in pipeline_list:
        entry_id = str(entry['_id'])
        meta_content = {
            'date': utilities._format_datestr(entry['date']),
            'date_added': entry['date_added'],
            'source': entry['source'],
            'story_title': entry['title'],
            'url': entry['url']
        }
        if 'parsed_sents' in entry:
            parsetrees = entry['parsed_sents']
        else:
            parsetrees = ''
        if 'corefs' in entry:
            corefs = entry['corefs']
            meta_content.update({'corefs': corefs})

        split_sents = _sentence_segmenter(entry['content'])
        # TODO Make the number of sents a setting
        sent_dict = {}
        for i, sent in enumerate(split_sents[:7]):
            if parsetrees:
                try:
                    tree = utilities._format_parsed_str(parsetrees[i])
                except IndexError:
                    tree = ''
                sent_dict[i] = {'content': sent, 'parsed': tree}
            else:
                sent_dict[i] = {'content': sent}

        content_dict = {'sents': sent_dict, 'meta': meta_content}
        holding[entry_id] = content_dict

    return holding


def _sentence_segmenter(paragr):
    """
    Function to break a string 'paragraph' into a list of sentences based on
    the following rules:

    1. Look for terminal [.,?,!] followed by a space and [A-Z]
    2. If ., check against abbreviation list ABBREV_LIST: Get the string
    between the . and the previous blank, lower-case it, and see if it is in
    the list. Also check for single-letter initials. If true, continue search
    for terminal punctuation
    3. Extend selection to balance (...) and "...". Reapply termination rules
    4. Add to sentlist if the length of the string is between MIN_SENTLENGTH
    and MAX_SENTLENGTH
    5. Returns sentlist

    Parameters
    ----------

    paragr: String.
            Content that will be split into constituent sentences.

    Returns
    -------

    sentlist: List.
                List of sentences.
    """
    # this is relatively high because we are only looking for sentences that
    # will have subject and object
    MIN_SENTLENGTH = 100
    MAX_SENTLENGTH = 512

    # sentence termination pattern used in sentence_segmenter(paragr)
    terpat = re.compile('[\.\?!]\s+[A-Z\"]')

    # source: LbjNerTagger1.11.release/Data/KnownLists/known_title.lst from
    # University of Illinois with editing
    ABBREV_LIST = [
        'mrs.', 'ms.', 'mr.', 'dr.', 'gov.', 'sr.', 'rev.', 'r.n.', 'pres.',
        'treas.', 'sect.', 'maj.', 'ph.d.', 'ed. psy.', 'proc.', 'fr.',
        'asst.', 'p.f.c.', 'prof.', 'admr.', 'engr.', 'mgr.', 'supt.', 'admin.',
        'assoc.', 'voc.', 'hon.', 'm.d.', 'dpty.', 'sec.', 'capt.', 'c.e.o.',
        'c.f.o.', 'c.i.o.', 'c.o.o.', 'c.p.a.', 'c.n.a.', 'acct.', 'llc.',
        'inc.', 'dir.', 'esq.', 'lt.', 'd.d.', 'ed.', 'revd.', 'psy.d.', 'v.p.',
        'senr.', 'gen.', 'prov.', 'cmdr.', 'sgt.', 'sen.', 'col.', 'lieut.',
        'cpl.', 'pfc.', 'k.p.h.', 'cent.', 'deg.', 'doz.', 'Fahr.', 'Cel.',
        'F.', 'C.', 'K.', 'ft.', 'fur.', 'gal.', 'gr.', 'in.', 'kg.', 'km.',
        'kw.', 'l.', 'lat.', 'lb.', 'lb per sq in.', 'long.', 'mg.',
        'mm.,, m.p.g.', 'm.p.h.', 'cc.', 'qr.', 'qt.', 'sq.', 't.', 'vol.',
        'w.', 'wt.'
    ]

    sentlist = []
    # controls skipping over non-terminal conditions
    searchstart = 0
    terloc = terpat.search(paragr)
    while terloc:
        isok = True
        if paragr[terloc.start()] == '.':
            if (paragr[terloc.start() - 1].isupper() and
                    paragr[terloc.start() - 2] == ' '):
                isok = False  # single initials
            else:
                # check abbreviations
                loc = paragr.rfind(' ', 0, terloc.start() - 1)
                if loc > 0:
                    if paragr[loc + 1:terloc.start() + 1].lower() in ABBREV_LIST:
                        isok = False
        if paragr[:terloc.start()].count('(') != paragr[:terloc.start()].count(
                ')'):
            isok = False
        if paragr[:terloc.start()].count('"') % 2 != 0:
            isok = False
        if isok:
            if (len(paragr[:terloc.start()]) > MIN_SENTLENGTH and
                    len(paragr[:terloc.start()]) < MAX_SENTLENGTH):
                sentlist.append(paragr[:terloc.start() + 2])
            paragr = paragr[terloc.end() - 1:]
            searchstart = 0
        else:
            searchstart = terloc.start() + 2

        terloc = terpat.search(paragr, searchstart)

    # add final sentence
    if (len(paragr) > MIN_SENTLENGTH and len(paragr) < MAX_SENTLENGTH):
        sentlist.append(paragr)

    return sentlist
