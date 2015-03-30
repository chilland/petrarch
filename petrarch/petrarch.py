# -*- coding: utf-8 -*-

from __future__ import print_function
from __future__ import unicode_literals

import os
import sys
import glob
import time
import logging
import argparse
import xml.etree.ElementTree as ET

# petrarch.py
#
# Automated event data coder
#
# SYSTEM REQUIREMENTS
# This program has been successfully run under Mac OS 10.10; it is standard
# Python 2.7 so it should also run in Unix or Windows.
#
# INITIAL PROVENANCE:
# Programmers:
#             Philip A. Schrodt
#             Parus Analytics
#             Charlottesville, VA, 22901 U.S.A.
#             http://eventdata.parusanalytics.com
#
#             John Beieler
#             Caerus Associates/Penn State University
#             Washington, DC / State College, PA, 16801 U.S.A.
#             http://caerusassociates.com
#             http://bdss.psu.edu
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

import PETRglobals  # global variables
import PETRreader  # input routines
import PETRwriter
import utilities

# ================================  PARSER/CODER GLOBALS  ================== #

ParseList = []  # linearized version of parse tree
ParseStart = 0  # first element to check (skips (ROOT, initial (S

# text that can be matched prior to the verb; this is stored in reverse order
UpperSeq = []
LowerSeq = []  # text that can be matched following the verb

SourceLoc = 0  # location of the source within the Upper/LowerSeq
TargetLoc = 0  # location of the target within the Upper/LowerSeq

SentenceID = ''  # ID line
EventCode = ''  # event code from the current verb
SourceCode = ''  # source code from the current verb
TargetCode = ''  # target code from the current verb

# ================================  VALIDATION GLOBALS  ==================== #

DoValidation = False  # using a validation file
ValidOnly = False  # only evaluate cases where <Sentence valid="true">
# validation mode : code triples that were produced; set in make_event_strings
CodedEvents = []
ValidEvents = []  # validation mode : code triples that should be produced
ValidInclude = []  # validation mode : list of categories to include
ValidExclude = []  # validation mode : list of categories to exclude
# validation mode :pause conditions: 1: always; -1 never; 0 only on error
# [default]
ValidPause = 0
ValidError = ''  # actual error code
ValidErrorType = ''  # expected error code

# ================================  DEBUGGING GLOBALS  ==================== #
# (comment out the second line in the pair to activate. Like you couldn't
# figure that out.)

# prints ParseList in evaluate_validation_record()/code_record() following NE
# assignment
ShowParseList = True
ShowParseList = False

# displays parse trees in read_TreeBank
ShowRTTrees = True
ShowRTTrees = False

# prints upper and lower sequences ParseList in make_check_sequences()
ShowCodingSeq = True
ShowCodingSeq = False

# prints pattern match info in check_verbs()
ShowPattMatch = True
ShowPattMatch = False

# prints search and intermediate strings in the (NE conversion
ShowNEParsing = True
ShowNEParsing = False

# prints intermediate strings in the compound markup
ShowMarkCompd = True
ShowMarkCompd = False

# ================== EXCEPTIONS ================== #


class DupError(Exception):  # template
    pass


class HasParseError(Exception):  # exit the coding due to parsing error
    pass


class SkipRecord(Exception):  # skip a validation record
    pass


class UnbalancedTree(Exception):  # unbalanced () in the parse tree
    pass


class IrregularPattern(Exception):  # problems were found at some point in
    pass                            # read_TreeBank


class CheckVerbsError(Exception):  # problems found in a specific pattern in
    pass                           # check_verbs [make local to that function?]

# ================== ERROR FUNCTIONS ================== #

def raise_ParseList_error(call_location_string):
    """
    Handle problems found at some point during the coding/evaluation of
    ParseList, and is called when the problem seems sufficiently important that
    the record should not be coded.  Logs the error and raises HasParseError.
    """
    global SentenceID, ValidError
    warningstr = call_location_string + ('; record skipped:'
                                         '{}'.format(SentenceID))
    logger = logging.getLogger('petr_log')
    logger.warning(warningstr)
    raise HasParseError

# ========================== DEBUGGING FUNCTIONS ========================== #


def show_tree_string(sent):
    """
    Indexes the () or (~in a string tree and prints as an indented list.
    """
    # show_tree_string() also prints the totals
    # call with ' '.join(list) to handle the list versions of the string
    newlev = False
    level = -1
    prevlevel = -1
    ka = 0
    nopen = 0
    nclose = 0
    sout = ''
    while ka < len(sent):
        if sent[ka] == '(':
            level += 1
            nopen += 1
            newlev = True
            if (level != prevlevel or
                'VP' == sent[ka + 1:ka + 3] or
                    'SB' == sent[ka + 1:ka + 3]):
                # new line only with change in level, also with (VP, (SB
                sout += '\n' + level * '  '
# sout += '\n' + level*'  '                         # new line for every (
            sout += '(-' + str(level) + ' '
        elif sent[ka] == ')' or sent[ka] == '~':
            nclose += 1
            prevlevel = level
            if not newlev:
                sout += '\n' + level * '  '
            if sent[ka] == ')':
                sout += str(level) + '-)'
            else:
                sout += str(level) + '~'
            level -= 1
            newlev = False
        else:
            sout += sent[ka]
        ka += 1
    print(sout)
    if nopen == nclose:
        print("Balanced:", end=' ')
    else:
        print("Unbalanced:", end=' ')
    print("Open", nopen, "Close", nclose, '\n')
    if nopen != nclose and PETRglobals.StoponError:
        raise HasParseError


def check_balance():
    """
    Check the (/~ count in a ParseList and raises UnbalancedTree if it is not
    balanced.
    """
    nopen = 0
    nclose = 0
    ka = 0
    while ka < len(ParseList):
        if ParseList[ka][0] == '(':
            nopen += 1
        elif ParseList[ka][0] == '~':
            nclose += 1
        ka += 1
    if nopen != nclose:
        raise UnbalancedTree

# ========================== VALIDATION FUNCTIONS ========================== #


def change_Config_Options(line):
    """
    Changes selected configuration options.
    """
    # need more robust error checking
    theoption = line['option']
    value = line['value']
    print("<Config>: changing", theoption, "to", value)
    if theoption == 'new_actor_length':
        try:
            PETRglobals.NewActorLength = int(value)
        except ValueError:
            logger.warning(
                "<Config>: new_actor_length must be an integer; "
                "command ignored")
    elif theoption == 'require_dyad':
        PETRglobals.RequireDyad = 'false' not in value.lower()
    elif theoption == 'stop_on_error':
        PETRglobals.StoponError = 'false' not in value.lower()
    elif 'comma_' in theoption:
        try:
            cval = int(value)
        except ValueError:
            logger.warning(
                "<Config>: comma_* value must be an integer; command ignored")
            return
        if '_min' in theoption:
            PETRglobals.CommaMin = cval
        elif '_max' in theoption:
            PETRglobals.CommaMax = cval
        elif '_bmin' in theoption:
            PETRglobals.CommaBMin = cval
        elif '_bmax' in theoption:
            PETRglobals.CommaBMax = cval
        elif '_emin' in theoption:
            PETRglobals.CommaEMin = cval
        elif '_emax' in theoption:
            PETRglobals.CommaEMax = cval
        else:
            logger.warning("<Config>: unrecognized option beginning with "
                           "comma_; command ignored")
    # insert further options here in elif clauses as this develops; also
    # update the docs in open_validation_file():
    else:
        logger.warning("<Config>: unrecognized option")


def evaluate_validation_record(item):
    """
    Read validation record, setting EventID and a list of correct coded events,
    code using read_TreeBank(), then check the results. Returns True if the
    lists of coded and expected events match or the event is skipped; false
    otherwise; also prints the mismatches.  Raises EOFError exception if EOF
    hit. Raises SkipRecord if <Skip> found or record is skipped due to
    In/Exclude category lists
    """
    global SentenceDate, SentenceID, SentenceCat, SentenceText, SentenceValid
    global CodedEvents, ValidEvents, ValidError, ValidErrorType
    global ValidInclude, ValidExclude, ValidPause, ValidOnly
    global ParseList
    # TODO: remove this and make read_TreeBank take it as an arg
    global treestr

    def extract_EventCoding_info(codings):
        """
        Extracts fields from <EventCoding record and appends to ValidEvents.
        Structure of ValidEvents
        noevents: empty list
        otherwise list of triples of [sourcecode, targetcode, eventcode]
        """
        # currently does not raise errors if the information is missing but
        # instead sets the fields to null strings
        global ValidEvents, ValidErrorType

        for coding in codings:
            event_attrs = coding.attrib
            if 'noevents' in event_attrs:
                ValidEvents = []
                return
            if 'error' in event_attrs:
                ValidEvents = []
                ValidErrorType = event_attrs['error']
                return
            else:
                ValidEvents.append([event_attrs['sourcecode'],
                                    event_attrs['targetcode'],
                                    event_attrs['eventcode']])

    ValidEvents = []  # code triples that should be produced
    # code triples that were produced; set in make_event_strings
    CodedEvents = []
    ValidErrorType = ''
    extract_Sentence_info(item.attrib)

    if ValidOnly and not SentenceValid:
        raise SkipRecord
        return True

    if len(ValidInclude) > 0 and SentenceCat not in ValidInclude:
        raise SkipRecord
        return True

    if len(ValidExclude) > 0 and SentenceCat in ValidExclude:
        raise SkipRecord
        return True

    extract_EventCoding_info(item.findall('EventCoding'))

    SentenceText = item.find('Text').text.replace('\n', '')

    if item.find('Skip'):  # handle skipping -- leave fin at end of tree
        raise SkipRecord
        return True

    parsed = item.find('Parse').text
    treestr = utilities._format_parsed_str(parsed)

    try:
        read_TreeBank()
    except IrregularPattern:
        if ValidErrorType != '':
            if ValidError != ValidErrorType:
                print(SentenceID,
                      'did not trigger the error "' + ValidErrorType + '"')
                return False
            else:
                return True
        else:
            print('\nSentence:', SentenceID, '[', SentenceCat, ']')
            print('Record triggered the error "' + ValidError + '"')
            return False

    print('\nSentence:', SentenceID, '[', SentenceCat, ']')
    print(SentenceText)

    disc = check_discards()

    if ((disc[0] == 0 and 'discard' in ValidErrorType) or
        (disc[0] == 1 and ValidErrorType != 'sentencediscard') or
            (disc[0] == 2 and ValidErrorType != 'storydiscard')):
        if disc[0] == 0:
            print('"' + ValidErrorType + '" was not triggered in ' + SentenceID)
        else:
            print(disc[1] + ' did not trigger  "' + ValidErrorType + '" in ' +
                  SentenceID)
        return False
    if disc[0] > 0:
        return True

    try:
        check_commas()
    except IndexError:
        raise_ParseList_error(
            'Initial index error on UpperSeq in get_loccodes()')

    assign_NEcodes()
    if False:
        print('EV-1:')
        show_tree_string(' '.join(ParseList))
    if ShowParseList:
        print('EVR-Parselist::', ParseList)

    check_verbs()  # can throw HasParseError which is caught in do_validation

    if len(ValidEvents) > 0:
        print('Expected Events:')
        for event in ValidEvents:
            print(event)

    if len(CodedEvents) > 0:
        print('Coded Events:')
        for event in CodedEvents:
            print(SentenceID)
            for st in event:
                if st:
                    print('\t' + st, end='')
                else:
                    print('\t---', end='')
            print()

    if (len(ValidEvents) == 0) and (len(CodedEvents) == 0):
        return True  # noevents option

    # compare the coded and expected events
    allokay = True
    ke = 0
    while ke < len(CodedEvents):  # check that all coded events have matches
        kv = 0
        while kv < len(ValidEvents):
            if (len(ValidEvents[kv]) > 3):
                kv += 1
                continue  # already matched
            else:
                if (CodedEvents[ke][0] == ValidEvents[kv][0]) and (
                    CodedEvents[ke][1] == ValidEvents[kv][1]
                ) and (CodedEvents[ke][2] == ValidEvents[kv][2]):
                    CodedEvents[ke].append('+')  # mark these as matched
                    ValidEvents[kv].append('+')
                    break
            kv += 1
        if (len(CodedEvents[ke]) == 3):
            print("No match for the coded event:", CodedEvents[ke])
            allokay = False
        ke += 1

    for vevent in ValidEvents:  # check that all expected events were matched
        if (len(vevent) == 3):
            print("No match for the expected event:", vevent)
            allokay = False
    return allokay


def open_validation_file(xml_root):
    """
    1. Opens validation file TextFilename as FIN
    2. After "</Environment>" found, closes FIN, opens ErrorFile, sets various
    validation options, then reads the dictionaries (exits if these are not set)
    3. Can raise MissingXML
    4. Can exit on EOFError
    """
    global ValidInclude, ValidExclude, ValidPause, ValidOnly
    logger = logging.getLogger('petr_log')

    environment = xml_root.find('Environment')
    if environment is None:
        print('Missing <Environment> block in validation file')
        print('Exiting program.')
        sys.exit()

    ValidInclude, ValidExclude, ValidPause, ValidOnly = _check_envr(environment)

    check1 = [len(PETRglobals.VerbFileName) == 0,
              len(PETRglobals.ActorFileList) == 0,
              len(PETRglobals.AgentFileName) == 0]
    if any(check1):
        print(
            "Missing <Verbfile>, <AgentFile> or <ActorFile> in validation file "
            "<Environment> block")
        print(
            "Exiting: This information is required for running a validation "
            "file")
        sys.exit()

    logger.info('Validation file: ' + PETRglobals.TextFileList[0] +
                '\nVerbs file: ' + PETRglobals.VerbFileName + '\nActors file: '
                + PETRglobals.ActorFileList[0] + '\nAgents file: ' +
                PETRglobals.ActorFileList[0] + '\n')
    if len(PETRglobals.DiscardFileName) > 0:
        logger.info('Discard file: ' + PETRglobals.DiscardFileName + '\n')
    if len(ValidInclude):
        logger.info('Include list: ' + ', '.join(ValidInclude) + '\n')
    if len(ValidExclude):
        logger.info('Exclude list: ' + ', '.join(ValidExclude) + '\n')

    print('Verb dictionary:', PETRglobals.VerbFileName)
    verb_path = utilities._get_data('data/dictionaries',
                                    PETRglobals.VerbFileName)
    PETRreader.read_verb_dictionary(verb_path)

    print('Actor dictionaries:', PETRglobals.ActorFileList[0])
    actor_path = utilities._get_data('data/dictionaries',
                                     PETRglobals.ActorFileList[0])
    PETRreader.read_actor_dictionary(actor_path)
    #    PETRreader.show_actor_dictionary('Actordict.txt')
    #    sys.exit()

    print('Agent dictionary:', PETRglobals.AgentFileName)
    agent_path = utilities._get_data('data/dictionaries',
                                     PETRglobals.AgentFileName)
    PETRreader.read_agent_dictionary(agent_path)

    if len(PETRglobals.DiscardFileName) > 0:
        print('Discard list:', PETRglobals.DiscardFileName)
        discard_path = utilities._get_data('data/dictionaries',
                                           PETRglobals.DiscardFileName)
        PETRreader.read_discard_list(discard_path)


def _check_envr(environ):
    for elem in environ:
        if elem.tag == 'Verbfile':
            PETRglobals.VerbFileName = elem.text

        if elem.tag == 'Actorfile':
            PETRglobals.ActorFileList[0] = elem.text

        if elem.tag == 'Agentfile':
            PETRglobals.AgentFileName = elem.text

        if elem.tag == 'Discardfile':
            PETRglobals.DiscardFileName = elem.text

        if elem.tag == 'Errorfile':
            print('This is deprecated. Using a different errorfile. ¯\_(ツ)_/¯')

        if elem.tag == 'Include':
            ValidInclude = elem.text.split()
            print('<Include> categories', ValidInclude)
            if 'valid' in ValidInclude:
                ValidOnly = True
                ValidInclude.remove('valid')
        else:
            ValidInclude = ''

        if elem.tag == 'Exclude':
            ValidExclude = elem.tag.split()
            print('<Exclude> categories', ValidExclude)
        else:
            ValidExclude = ''

        if elem.tag == 'Pause':
            theval = elem.text
            if 'lways' in theval:
                ValidPause = 1  # skip first char to allow upper/lower case
            elif 'ever' in theval:
                ValidPause = 2
            elif 'top' in theval:
                ValidPause = 3
            else:
                ValidPause = 0

    return ValidInclude, ValidExclude, ValidPause, ValidOnly

# ================== TEXTFILE INPUT ================== #


def read_TreeBank():
    """
    Reads parsed sentence in the Penn TreeBank II format and puts the linearized
    version in the list ParseList. Sets ParseStart. Leaves global input file fin
    at line following </parse>. The routine is appears to be agnostic towards
    the line-feed and tab formatting of the parse tree

    TO DO <14.09.03>: Does this handle an unexpected EOF error?

    TO DO <14.09.03>: This really belongs as a separate module and the code
    seems sufficiently stable now that this could be done
    """

    global ParseList, ParseStart
    global treestr
    global fullline
    global ncindex

    def check_irregulars(knownerror=''):
        """
        Checks for some known idiosyncratic ParseList patterns that indicate
        problems in the the input text or, if knownrecord != '', just raises an
        already detected error. In either case, logs the specific issue, sets
        the global ValidError (for unit tests) and raises IrregularPattern.
        Currently tracking:
           -- bad_input_parse
           -- empty_nplist
           -- bad_final_parse
           -- get_forward_bounds
           -- get_enclosing_bounds
           -- resolve_compounds
           -- get_NE_error
           -- dateline [pattern]
       """
        global ValidError
        if knownerror:
            if knownerror == 'bad_input_parse':
                warningstr = '<Parse>...</Parse> input was not balanced; '
                'record skipped: {}'
            elif knownerror == 'empty_nplist':
                warningstr = 'Empty np_list in read_Tree; record skipped: {}'
            elif knownerror == 'bad_final_parse':
                warningstr = 'ParseList unbalanced at end of read_Tree; '
                'record skipped: {}'
            elif knownerror == 'get_forward_bounds':
                warningstr = 'Upper bound error in get_forward_bounds in '
                'read_Tree; record skipped: {}'
            elif knownerror == 'get_enclosing_bounds':
                warningstr = 'Lower bound error in get_enclosing_bounds in '
                'read_Tree; record skipped: {}'
            elif knownerror == 'resolve_compounds':
                warningstr = 'get_NE() error in resolve_compounds() in '
                'read_Tree; record skipped: {}'
            elif knownerror == 'get_NE_error':
                warningstr = 'get_NE() error in main loop of read_Tree; record '
                'skipped: {}'
            else:
                warningstr = """Unknown error type encountered in """
                """check_irregulars() --------- this is a programming bug """
                """but nonetheless the record was skipped: {}"""
            logger = logging.getLogger('petr_log')
            logger.warning(warningstr.format(SentenceID))
            ValidError = knownerror
            raise IrregularPattern

        ntag = 0
        taglist = []
        ka = 0
        while ka < len(ParseList):
            if ParseList[ka][0] == '(':
                taglist.append(ParseList[ka])
                ntag += 1
                if ntag > 2:
                    break  # this is all we need for dateline
            ka += 1
        if taglist[:3] == ['(ROOT', '(NE', '(NEC']:
            logger = logging.getLogger('petr_log')
            logger.warning(
                'Dateline pattern found in ParseList; record skipped: '
                '{}'.format(SentenceID))
            ValidError = 'dateline'
            raise IrregularPattern

    def get_NE(NPphrase):
        """
        Convert (NP...) ) to NE: copies any (NEC phrases with markup, remainder
        of the phrase without any markup Can raise IrregularPattern, which is
        caught and re-raised at the calling point
        """
        nplist = ['(NE --- ']
        seg = NPphrase.split()
        if ShowNEParsing:
            print('List:', seg)
            print("gNE input tree", end=' ')
            show_tree_string(NPphrase)
            print('List:', seg)
        ka = 1
        while ka < len(seg):
            if seg[ka] == '(NEC':  # copy the phrase
                nplist.append(seg[ka])
                ka += 1
                nparen = 1  # paren count
                while nparen > 0:
                    if ka >= len(seg):
                        raise IrregularPattern
                    if seg[ka][0] == '(':
                        nparen += 1
                    elif seg[ka] == ')':
                        nparen -= 1
                    nplist.append(seg[ka])
                    ka += 1
            # copy the phrase without the markup
            elif seg[ka][0] != '(' and seg[ka] != ')':
                nplist.append(seg[ka])
                ka += 1
            else:
                ka += 1

        nplist.append(')')

        return nplist

    def get_forward_bounds(ka):
        """
        Returns the bounds of a phrase in treestr that begins at ka, including
        the final space.
        """
        global treestr  # <13.12.07> see note above
        kb = ka + 1
        nparen = 1  # paren count
        while nparen > 0:
            if kb >= len(treestr):
                check_irregulars('get_forward_bounds')
            if treestr[kb] == '(':
                nparen += 1
            elif treestr[kb] == ')':
                nparen -= 1
            kb += 1

        return [ka, kb]

    def get_enclosing_bounds(ka):
        """
        Returns the bounds of a phrase in treestr that encloses the phrase
        beginning at ka
        """
        global treestr  # <13.12.07> see note above
        kstart = ka - 1
        nparen = 0  # paren count
        while nparen <= 0:  # back out to the phrase tag that encloses this
            if kstart < 0:
                check_irregulars('get_enclosing_bounds')
            if treestr[kstart] == '(':
                nparen += 1
            elif treestr[kstart] == ')':
                nparen -= 1
            kstart -= 1
        return [kstart + 1, get_forward_bounds(kstart + 1)[1]]

    def mark_compounds():
        """
        Determine the inner-most phrase of each CC and mark: -- NEC: compound
        noun phrase for (NP tags -- CCP: compound phrase for (S and (VP tags
        [possibly add (SBAR to this?] otherwise just leave as CC
        """
        global treestr

        ka = -1
        while ka < len(treestr):
            ka = treestr.find('(CC', ka + 3) #
            if ka < 0:
                break
            kc = treestr.find(')', ka + 3)
            bds = get_enclosing_bounds(ka)
            kb = bds[0]
            if ShowMarkCompd:
                print('\nMC1:', treestr[kb:])
            # these aren't straightforward compound noun phrases we are
            # looking for
            if '(VP' in treestr[bds[0]:bds[1]] or '(S' in treestr[bds[0]:bds[1]]:
                # convert CC to CCP, though <14.05.12> we don't actually do
                # anything with this: (NEC is a sufficient trigger for
                # additional processing of compounds
                treestr = treestr[:ka + 3] + 'P' + treestr[ka + 3:]
                if ShowMarkCompd:
                    print('\nMC2:', treestr[kb:])
            # nested compounds: don't go there...
            elif treestr[bds[0]:bds[1]].count('(CC') > 1:
                # convert CC to CCP: see note above
                treestr = treestr[:ka + 4] + 'P' + treestr[ka + 4:]
                if ShowMarkCompd:
                    print('\nMC3:', treestr[kb:])
            elif treestr[kb + 1:kb + 3] == 'NP':
                # make sure we actually have multiple nouns in the phrase
                if treestr.count('(N', bds[0], bds[1]) >= 3:
                    treestr = treestr[:kb + 2] + 'EC' + treestr[kb + 3:]
                    # convert NP to NEC
                    if ShowMarkCompd:
                        print('\nMC4:', treestr[kb:])

    def resolve_compounds(ka):
        """
        Assign indices, eliminates the internal commas and (CC, and duplicate
        any initial adjectives inside a compound.
        """
        global treestr, fullline

        necbds = get_forward_bounds(ka)  # get the bounds of the NEC phrase
        if ShowMarkCompd:
            print('rc/RTB: NEC:', necbds, treestr[necbds[0]:necbds[1]])
        ka += 4

        adjlist = []  # get any adjectives prior to first noun
        while not treestr.startswith('(NP',
                                     ka) and not treestr.startswith('(NN', ka):
            if treestr.startswith('(JJ', ka):
                npbds = get_forward_bounds(ka)
                if ShowMarkCompd:
                    print('rc/RTB-1: JJ:', npbds, treestr[npbds[0]:npbds[1]])
                adjlist.extend(treestr[npbds[0]:npbds[1]].split())
            ka += 1

        while ka < necbds[1]:  # convert all of the NP, NNS and NNP to NE
            if treestr.startswith('(NP', ka) or treestr.startswith('(NN', ka):
                npbds = get_forward_bounds(ka)
                if ShowMarkCompd:
                    print('rc/RTB-1: NE:', npbds, treestr[npbds[0]:npbds[1]])
                # just a single element, so get it
                if treestr.startswith('(NN', ka):
                    seg = treestr[npbds[0]:npbds[1]].split()
                    nplist = ['(NE --- ']
                    if len(adjlist) > 0:
                        nplist.extend(adjlist)
                    nplist.extend([seg[1], ' ) '])
                else:
                    try:
                        nplist = get_NE(treestr[npbds[0]:npbds[1]])
                    except IrregularPattern:
                        check_irregulars('resolve_compounds')

                if ShowMarkCompd:
                    print('rc/RTB-2: NE:', nplist)
                for kb in range(len(nplist)):
                    fullline += nplist[kb] + ' '
                ka = npbds[1]
            ka += 1
        fullline += ' ) '  # closes the nec
        if ShowMarkCompd:
            print('rc/RTB3: NE:', fullline)
        return necbds[1] + 1

    def reduce_SBAR(kstart):
        """
        Collapse SBAR beginning at kstart to a string without any markup; change
        clause marker to SBR, which is subsequently eliminated
        """
        global treestr

        bds = get_enclosing_bounds(kstart + 5)
        frag = ''
        segm = treestr[bds[0]:bds[1]]
        kc = 0
        while kc < len(segm):
            kc = segm.find(' ', kc)
            if kc < 0:
                break
            if segm[kc + 1] != '(':  # skip markup, just get words
                kd = segm.find(' )', kc)
                frag += segm[kc:kd]
                kc = kd + 3
            else:
                kc += 2
# bound with '(SBR ' and ' )'
        treestr = treestr[:bds[0]] + '(SBR ' + frag + treestr[bds[1] - 2:]

    def process_preposition(ka):
        """
        Process (NP containing a (PP and return an nephrase: if this doesn't
        have a simple structure of  (NP (NP ...) (PP...) (NP/NEC ...)) without
        any further (PP -- i.e. multiple levels of prep phrases -- it returns a
        null string.
        """

        global treestr, ncindex

        bds = get_enclosing_bounds(ka)  # this should be a (NP (NP
        if treestr.startswith('(NP (NP', bds[0]):
            nepph = '(NP '  # placeholder: this will get converted
            npbds = get_forward_bounds(bds[0] + 4)  # get the initial (NP
            nepph += treestr[npbds[0] + 4:npbds[1] - 2]
        elif treestr.startswith('(NP (NEC', bds[0]):
            nepph = '(NP (NEC '  # placeholder:
            npbds = get_forward_bounds(bds[0] + 4)  # get the initial (NEC
            # save the closing ' ) '
            nepph += treestr[npbds[0] + 4:npbds[1] + 1]
        else:
            return ''  # not what we are expecting, so bail
# get the preposition and transfer it
        ka = treestr.find('(IN ', npbds[1])
        nepph += treestr[ka:treestr.find(' ) ', ka + 3) + 3]
        # find first (NP or (NEC after prep
        kp = treestr.find('(NP ', ka + 4, bds[1])
        kec = treestr.find('(NEC ', ka + 4, bds[1])
        if kp < 0 and kec < 0:
            return ''  # not what we are expecting, so bail
        if kp < 0:
            kp = len(treestr)  # no (NP gives priority to (NEC and vice versa
        if kec < 0:
            kec = len(treestr)
        if kp < kec:
            kb = kp
        else:
            kb = kec
        npbds = get_forward_bounds(kb)
        if '(PP' in treestr[npbds[0]:npbds[1]]:
            return ('')
            # there's another level of (PP here  <14.04.21: can't we just
            # reduce this per (SBR?
        # leave the (NEC in place. <14.01.15> It should be possible to add an
        # index here, right?
        if treestr[kb + 2] == 'E':
            nepph += treestr[kb:npbds[1] + 1]  # pick up a ') '
        else:
            # skip the (NP and pick up the final ' ' (we're using this to close
            # the original (NP
            nepph += treestr[npbds[0] + 4:npbds[1] - 1]
        if '(SBR' in treestr[npbds[1]:]:  # transfer the phrase
            kc = treestr.find('(SBR', npbds[1])
            nepph += treestr[kc:treestr.find(') ', kc) + 2]
        nepph += ')'  # close the phrase
        # exst = '\"'+ nepph + '\"'
        # add quotes to see exactly what we've got here
        return nepph

    def filter_treestr():
        """
        Filters known problematic strings in treestr
        """
        global treestr
        if '~' in treestr:
            treestr = treestr.replace('~', '-TILDA-')

    logger = logging.getLogger('petr_log')
    fullline = ''
    vpindex = 1
    npindex = 1
    ncindex = 1

    if ShowRTTrees:
        print('RT1 treestr:', treestr)
        print('RT1 count:', treestr.count('('), treestr.count(')'))
        show_tree_string(treestr)
    if treestr.count('(') != treestr.count(')'):
        check_irregulars('bad_input_parse')

    filter_treestr()

    mark_compounds()

    if ShowRTTrees:
        print('RT1.5 count:', treestr.count('('), treestr.count(')'))

    ka = 0
    while ka < len(treestr):
        if treestr.startswith('(NP ', ka):
            npbds = get_forward_bounds(ka)

            ksb = treestr.find('(SBAR ', npbds[0],
                               npbds[1])  # reduce (SBARs inside phrase
            while ksb >= 0:
                reduce_SBAR(ksb)
                # recompute the bounds because treestr has been modified
                npbds = get_forward_bounds(ka)
                ksb = treestr.find('(SBAR ', npbds[0], npbds[1])
            nephrase = ''
            if ShowNEParsing:
                print('BBD: ', treestr[npbds[0]:npbds[1]])
            if '(POS' in treestr[ka + 3:npbds[1]]:  # get the (NP possessive
                kb = treestr.find('(POS', ka + 4)
                nephrase = treestr[ka + 4:kb - 1]  # get string prior to (POS
                if treestr[kb + 12] == 's':
                    incr = 14
                else:
                    incr = 13  # allow for (POS ')
# skip over (POS 's) and get the remainder of the NP
                nephrase += ' ' + treestr[kb + incr:npbds[1]]
                if ShowNEParsing:
                    print('RTPOS: NE:', nephrase)

            elif '(PP' in treestr[ka + 3:npbds[1]]:  # prepositional phrase
                if False:
                    print('PPP-1: ', treestr[ka:npbds[1]])
                    print('PPP-1a: ', treestr.find('(PP', ka + 3, npbds[1]), ka,
                          npbds[1])
                    print('PPP-1b: ',
                          get_enclosing_bounds(treestr.find('(PP', ka + 3,
                                                            npbds[1])))
                nephrase = process_preposition(treestr.find('(PP', ka + 3,
                                                            npbds[1]))
                if ShowNEParsing:
                    print('RTPREP: NE:', nephrase)

            # no further (NPs, so convert to NE
            elif '(NP' not in treestr[ka + 3:npbds[1]
                                     ] and '(NEC' not in treestr[ka + 3:npbds[1]]:
                nephrase = treestr[ka:npbds[1]]
                if ShowNEParsing:
                    print('RTNP: NE:', nephrase)

            if len(nephrase) > 0:
                try:
                    nplist = get_NE(nephrase)
                except IrregularPattern:
                    check_irregulars('get_NE_error')

                if not nplist:
                    check_irregulars('empty_nplist')
                for kb in range(len(nplist)):
                    fullline += nplist[kb] + ' '
                ka = npbds[1] + 1
            else:
                fullline += '(NP' + str(npindex) + ' '  # add index
                npindex += 1
                ka += 4

        elif treestr.startswith('(NEC ', ka):
            fullline += '(NEC' + str(ncindex) + ' '
            ncindex += 1
            ka = resolve_compounds(ka)

        elif treestr.startswith('(VP ', ka):  # assign index to VP
            fullline += '(VP' + str(vpindex) + ' '
            vpindex += 1
            ka += 4
        else:
            fullline += treestr[ka]
            ka += 1

    # convert the text to ParseList format; convert ')' to ~XX tags
    ParseList = fullline.split()
    kopen = 0
    kclose = 0
    for item in ParseList:
        if item.startswith('('):
            kopen += 1
        elif item == ')':
            kclose += 1
    if ShowRTTrees:
        print('RT2 count:', kopen, kclose)
    ka = 0
    opstack = []
    while ka < len(ParseList):
        if ParseList[ka][0] == '(':
            opstack.append(ParseList[ka][1:])
        if ParseList[ka][0] == ')':
            if len(opstack) == 0:
                break
            op = opstack.pop()
            ParseList[ka] = '~' + op
        ka += 1

    if ShowRTTrees:
        print('RT2:', ParseList)
        show_tree_string(' '.join(ParseList))

    ParseStart = 2  # skip (ROOT (S

    check_irregulars()
    # this can raise IrregularPattern which is caught by try: read_TreeBank

    try:
        check_balance()
    except UnbalancedTree:
        check_irregulars('bad_final_parse')

# ================== CODING ROUTINES  ================== #


def get_loccodes(thisloc):
    """
    Returns the list of codes from a compound, or just a single code if not
    compound

    Extracting noun phrases which are not in the dictionary: If no actor or
    agent generating a non-null code can be found using the source/target rules,
    PETRARCH can output the noun phrase in double-quotes. This is controlled by
    the configuration file option new_actor_length, which is set to an integer
    which gives the maximum length for new actor phrases extracted. If this is
    set to zero [default], no extraction is done and the behavior is the same as
    TABARI. Setting this to a large number will extract anything found in a (NP
    noun phrase, though usually true actors contain a small number of words.
    """
    global UpperSeq, LowerSeq, codelist, StoryEventList

    StoryEventList = []

    def get_ne_text(neloc, isupperseq):
        """
        Returns the text of the phrase from UpperSeq/LowerSeq starting at neloc.
        """
        if isupperseq:
            acphr = UpperSeq[neloc - 1]
            ka = neloc - 2  # UpperSeq is stored in reverse order
            while ka >= 0 and UpperSeq[ka][0] != '~':
                # we can get an unbalanced sequence when multi-word verbs cut
                # into the noun phrase: see DEMO-30 in unit-tests
                acphr += ' ' + UpperSeq[ka]
                ka -= 1
        else:
            acphr = LowerSeq[neloc + 1]
            ka = neloc + 2
            while LowerSeq[ka][0] != '~':
                acphr += ' ' + LowerSeq[ka]
                ka += 1

        return acphr

    def add_code(neloc, isupperseq):
        """
        Appends the code or phrase from UpperSeq/LowerSeq starting at neloc.
        isupperseq determines the choice of sequence

        If PETRglobals.WriteActorText is True, root phrase is added to the code
        following the string PETRglobals.TextPrimer
        """
        global UpperSeq, LowerSeq, codelist

        if isupperseq:
            acneitem = UpperSeq[neloc]  # "add_code neitem"
        else:
            acneitem = LowerSeq[neloc]
        accode = acneitem[acneitem.find('>') + 1:]
        if accode != '---':
            codelist.append(accode)
        elif PETRglobals.NewActorLength > 0:  # get the phrase
            acphr = '"' + get_ne_text(neloc, isupperseq) + '"'
            if acphr.count(' ') < PETRglobals.NewActorLength:
                codelist.append(acphr)
            else:
                codelist.append(accode)
            if PETRglobals.WriteActorRoot:
                codelist[-1] += PETRglobals.RootPrimer + '---'

        if PETRglobals.WriteActorText and len(codelist) > 0:
            codelist[-1] += PETRglobals.TextPrimer + get_ne_text(neloc,
                                                                 isupperseq)

    codelist = []
    if thisloc[1]:
        try:
            neitem = UpperSeq[thisloc[0]]
        except IndexError:
            raise_ParseList_error(
                'Initial index error on UpperSeq in get_loccodes()')

# extract the compound codes from the (NEC ... ~NEC sequence
        if '(NEC' in neitem:
            ka = thisloc[0] - 1  # UpperSeq is stored in reverse order
            while '~NEC' not in UpperSeq[ka]:
                if '(NE' in UpperSeq[ka]:
                    add_code(ka, True)
                ka -= 1
                if ka < 0:
                    raise_ParseList_error(
                        'Bounds underflow on UpperSeq in get_loccodes()')
        else:
            add_code(thisloc[0], True)
    else:
        try:
            neitem = LowerSeq[thisloc[0]]
        except IndexError:
            raise_ParseList_error(
                'Initial index error on LowerSeq in get_loccodes()')
        StoryEventList.append([SentenceID])
        for event in CodedEvents:
            StoryEventList.append(event)
            print(SentenceID + '\t' + event[0] + '\t' + event[1] + '\t' +
                  event[2])
        if '(NEC' in neitem:  # extract the compound codes
            ka = thisloc[0] + 1
            while '~NEC' not in LowerSeq[ka]:
                if '(NE' in LowerSeq[ka]:
                    add_code(ka, False)
                ka += 1
                if ka >= len(LowerSeq):
                    raise_ParseList_error(
                        'Bounds overflow on LowerSeq in get_loccodes()')
        else:
            add_code(thisloc[0], False)
    if len(codelist) == 0:  # this can occur if all codes in an (NEC are null
        codelist = ['---']
    return codelist


def find_source():
    """
    Assign SourceLoc to the first coded or compound (NE in the UpperSeq; if
    neither found then first (NE with --- code Note that we are going through
    the sentence in normal order, so we go through UpperSeq in reverse order.
    Also note that this matches either (NE and (NEC: these are processed
    differently in make_event_string()
    """
    global UpperSeq, SourceLoc

    kseq = len(UpperSeq) - 1
    while kseq >= 0:
        if ('(NEC' in UpperSeq[kseq]):
            SourceLoc = [kseq, True]
            return
        if ('(NE' in UpperSeq[kseq]) and ('>---' not in UpperSeq[kseq]):
            SourceLoc = [kseq, True]
            return
        kseq -= 1
        # failed, so check for
        # uncoded source
    kseq = len(UpperSeq) - 1
    while kseq >= 0:
        if ('(NE' in UpperSeq[kseq]):
            SourceLoc = [kseq, True]
            return
        kseq -= 1


def find_target():
    """
    Assigns TargetLoc

    Priorities for assigning target:
        1. first coded (NE in LowerSeq that does not have the same code as
        SourceLoc; codes are not checked with either SourceLoc or the
        candidate target are compounds (NEC
        2. first null-coded (NE in LowerSeq ;
        3. first coded (NE in UpperSeq -- that is, searching backwards from
        the verb -- that does not have the same code as SourceLoc;
        4. first null-coded (NE in UpperSeq
    """

    global UpperSeq, LowerSeq, SourceLoc, TargetLoc
    srccodelist = get_loccodes(SourceLoc)
    if len(srccodelist) == 1:
        srccode = '>' + srccodelist[0]
    else:
        srccode = '>>>>'  # placeholder for a compound; this will not occur
    kseq = 0
    while kseq < len(LowerSeq):
        if ('(NE' in LowerSeq[kseq]) and ('>---' not in LowerSeq[kseq]):
            if (srccode not in LowerSeq[kseq]):
                TargetLoc = [kseq, False]
                return
        kseq += 1
        # failed, so check for
        # uncoded target in
        # LowerSeq
    kseq = 0
    while kseq < len(LowerSeq):
        # source might also be uncoded now
        if ('(NE' in LowerSeq[kseq]) and ('>---' in LowerSeq[kseq]):
            TargetLoc = [kseq, False]
            return
        kseq += 1

    # still didn't work, so look in UpperSeq going away from the verb, so we
    # increment through UpperSeq
    kseq = 0
    while kseq < len(UpperSeq):
        if ('(NE' in UpperSeq[kseq]) and ('>---' not in UpperSeq[kseq]):
            if (srccode not in UpperSeq[kseq]):
                TargetLoc = [kseq, True]
                return
        kseq += 1
        # that failed as well,
        # so finally check for
        # uncoded target
    kseq = 0
    while kseq < len(UpperSeq):
        if ('(NE' in UpperSeq[kseq]) and ('>---' in UpperSeq[kseq]):
            # needs to be a different (NE from source
            if (kseq != SourceLoc[0]):
                TargetLoc = [kseq, True]
                return
        kseq += 1


def get_upper_seq(kword):
    """
    Generate the upper sequence starting from kword; Upper sequence currently
    terminated by ParseStart, ~S or ~,
    """
    global ParseList, ParseStart
    global UpperSeq

    UpperSeq = []
    while kword >= ParseStart:
        if ('~,' in ParseList[kword]):
            break
        if ('(NE' == ParseList[kword]):
            code = UpperSeq.pop()  # remove the code
            UpperSeq.append(ParseList[kword] + '<' + str(kword) + '>' + code)
            # <pas 13.07.26> See Note-1
        elif ('NEC' in ParseList[kword]):
            UpperSeq.append(ParseList[kword])
        elif ('~NE' in ParseList[kword]):
            UpperSeq.append(ParseList[kword])
        elif (ParseList[kword][0] != '(') and (ParseList[kword][0] != '~'):
            UpperSeq.append(ParseList[kword])
        kword -= 1
        if kword < 0:
            raise_ParseList_error('Bounds underflow in get_upper_seq()')
            # error is handled in check_verbs
            return

    if ShowCodingSeq:
        print("Upper sequence:", UpperSeq)


def get_lower_seq(kword, endtag):
    """
    Generate the lower sequence starting from kword; lower sequence includes
    only words in the VP
    """
    global ParseList
    global LowerSeq

    LowerSeq = []
    while (endtag not in ParseList[kword]):  # limit to the verb phrase itself
        if ('(NE' == ParseList[kword]):
            LowerSeq.append(
                ParseList[kword] + '<' + str(kword) + '>' + ParseList[kword + 1]
            )  # <pas 13.07.26> See Note-1
            kword += 1  # skip code
        elif ('NEC' in ParseList[kword]):
            LowerSeq.append(ParseList[kword])
        elif ('~NE' in ParseList[kword]):
            LowerSeq.append(ParseList[kword])
        elif (ParseList[kword][0] != '(') and (ParseList[kword][0] != '~'):
            LowerSeq.append(ParseList[kword])
        kword += 1
        if kword >= len(ParseList):
            # <14.04.23>: need to just set this to len(ParseList)?
            raise_ParseList_error('Bounds overflow in get_lower_seq()')
            # error is handled in check_verbs
            return  # not needed, right?

    if ShowCodingSeq:
        print("Lower sequence:", LowerSeq)


def make_check_sequences(verbloc, endtag):
    """
    Create the upper and lower sequences to be checked by the verb patterns
    based on the verb at ParseList[verbloc].
    """

    get_upper_seq(verbloc - 1)
    get_lower_seq(verbloc + 1, endtag)


def make_multi_sequences(multilist, verbloc, endtag):
    """
    Check if the multi-word list in multilist is valid for the verb at
    ParseList[verbloc], then create the upper and lower sequences to be checked
    by the verb patterns. Lower sequence includes only words in the VP; upper
    sequence currently terminated by ParseStart, ~S or ~, Returns False if the
    multilist is not valid, True otherwise.
    """
    global ParseList, ParseStart

    logger = logging.getLogger('petr_log')
    ka = 1
    if multilist[0]:  # words follow the verb
        kword = verbloc + 1
        while ka < len(multilist):
            if (ParseList[kword][0] != '(') and (ParseList[kword][0] != '~'):
                if ParseList[kword] == multilist[ka]:
                    ka += 1
                else:
                    return False
            kword += 1
        get_upper_seq(verbloc - 1)
        get_lower_seq(kword, endtag)
        return True
    else:
        kword = verbloc - 1
        while ka < len(multilist):
            #            print('@@@',kword,ParseList[kword])
            if (ParseList[kword][0] != '(') and (ParseList[kword][0] != '~'):
                if ParseList[kword] == multilist[ka]:
                    ka += 1
                else:
                    return False
            kword -= 1
        print("MMS-2", verbloc, ParseList[verbloc], endtag)
        get_upper_seq(kword)
        get_lower_seq(verbloc + 1, endtag)
        return True


def verb_pattern_match(patlist, aseq, isupperseq):
    """
    Attempts to match patlist against UpperSeq or LowerSeq; returns True on
    success.
    """
    # Can set SourceLoc and TargetLoc for $, + and % tokens
    # Still need to handle %

    global SourceLoc, TargetLoc
    global kpatword, kseq

    ShowVPM = True
    ShowVPM = False

    def find_ne(kseq):
        # return the location of the (NE element in aseq starting from kseq,
        # which is inside an NE
        ka = kseq

        while '(NE' not in aseq[ka]:
            if isupperseq:
                ka += 1
                if ka >= len(aseq):
                    raise_ParseList_error('Overflow error in find_ne(kseq) in '
                                          'verb_pattern_match()')
            else:
                ka -= 1
                if ka < 0:
                    raise_ParseList_error(
                        'Underflow error in find_ne(kseq) in '
                        'verb_pattern_match()')

        return ka

    def syn_match(isupperseq):
        global kseq, kpatword

        if patlist[kpatword] in PETRglobals.VerbDict:
            # first try the single word cases
            if aseq[kseq] not in PETRglobals.VerbDict[patlist[kpatword]]:
                for words in PETRglobals.VerbDict[patlist[kpatword]]:
                    if ' ' in words:  # try to match a phrase
                        # <14.05.08> may want to pre-split this and store as a
                        # list
                        wordlist = words.split()
                        # need to go through phrase in reverse in upperseq
                        if isupperseq:
                            ka = len(wordlist) - 1
                            offset = 0
                            while (ka >= 0) and (
                                (kseq + offset) < len(aseq)
                            ) and (aseq[kseq + offset] == wordlist[ka]):
                                ka -= 1  # will this handle reverse matches?
                                offset += 1
                            if ka < 0:
                                ka = len(wordlist)  # triggers match below
                        else:
                            ka = 0
                            while (ka < len(wordlist)) and (
                                (kseq + ka) < len(aseq)
                            ) and (aseq[kseq + ka] == wordlist[ka]):
                                ka += 1
                        if ka == len(wordlist):
                            # last_seq() will also increment
                            kseq += len(wordlist) - 1

                            return True
                return False
            else:
                return True
        else:
            # throw an error here, but actually should trap these in
            # read_verb_dict so the check won't be needed
            print("&Error:", patlist[kpatword], "not in dictionary")

    def last_seqword():
        global kseq
        kseq += 1
        if kseq >= len(aseq):
            return True  # hit end of sequence before full pattern matched
        else:
            return False

    def last_patword():
        global kpatword
        kpatword += 2  # skip connector
        if kpatword >= len(patlist):
            return True
        else:
            return False

    def no_skip():
        global kpatword
        if patlist[kpatword - 1] == ' ':
            if last_seqword():
                return True
            else:
                return False
        else:
            return True

    if ShowVPM:
        print("VPM-0", patlist, aseq, str(isupperseq))
    if len(patlist) == 0:
        return True  # nothing to evaluate, so okay
    if len(aseq) == 0:
        return False  # nothing to match, so fails
    insideNE = False
    inNEC = False  # do same thing but "insideNEC" is an invitation to a typo
    kpatword = 1  # first word, skipping connector
    kseq = 0
    while kpatword < len(patlist):  # iterate over the words in the pattern
        if ShowVPM:
            print("VPM-1: pattern", patlist[kpatword])

        if len(patlist[kpatword]) == 0:
            if last_patword():  # nothing to see here, move along, move along.
                return False  # Though in fact this should not occur
            continue

        if ('~NE' in aseq[kseq]) or ('(NE' in aseq[kseq]):
            if len(aseq[kseq]) > 3 and aseq[kseq][3] == 'C':
                if last_seqword():
                    return False  # end of sequence before full pattern matched
                inNEC = not inNEC

            else:
                if last_seqword():
                    return False  # end of sequence before full pattern matched
                insideNE = not insideNE

        elif len(patlist[kpatword]) == 1:  # deal with token assignments here
            if insideNE or inNEC:
                if insideNE:
                    if patlist[kpatword] == '$':
                        SourceLoc = [find_ne(kseq), isupperseq]
                    elif patlist[kpatword] == '+':
                        TargetLoc = [find_ne(kseq), isupperseq]

                    elif patlist[kpatword] == '^':  # skip to the end of the (NE
                        while '~NE' not in aseq[kseq]:
                            if isupperseq:
                                kseq -= 1
                            else:
                                kseq += 1
                            if kseq < 0 or kseq >= len(aseq):
                                # at this point some sort of markup we can't
                                # handle
                                raise_ParseList_error(
                                    "find_ne(kseq) in skip assessment,"
                                    "verb_pattern_match()")
                        if ShowVPM:
                            print("VPM/FN-1: Found NE:", kseq,
                                  aseq[kseq])  # debug
                        insideNE = isupperseq

                elif patlist[kpatword] == '%':  # deal with compound
                    ka = kseq
                    while '(NEC' not in aseq[ka]:
                        if isupperseq:
                            ka += 1
                        else:
                            ka -= 1
                        if ka < 0 or ka >= len(aseq):
                            return False
                    SourceLoc = [ka, isupperseq]
                    TargetLoc = [ka, isupperseq]

                if ShowVPM:
                    print('vpm-mk3')
                    print("VPM-4: Token assignment ", patlist[kpatword],
                          aseq[find_ne(kseq)])
                if last_patword():
                    return True
                if last_seqword():
                    return False
            elif patlist[kpatword - 1] == ' ':
                if last_seqword():
                    return False
            else:
                return False

        elif patlist[kpatword][0] == '&':  # match a synset
            if syn_match(isupperseq):
                if ShowVPM:
                    print("VPM-3: synMatch ", kseq, patlist[kpatword],
                          aseq[kseq])
                if last_patword():
                    return True
                if last_seqword():
                    return False
            else:
                if ShowVPM:
                    # debug
                    print("VPM-2: Synset Fail ", patlist[kpatword], aseq[kseq])
                if no_skip():
                    return False

        elif patlist[kpatword] != aseq[kseq]:
            if ShowVPM:
                print("VPM-2: Fail ", patlist[kpatword], aseq[kseq])  # debug
            if no_skip():
                return False

        else:  # match successful to this point
            if ShowVPM:
                print("VPM-3: Match ", patlist[kpatword], aseq[kseq])  # debug
            if last_patword():
                return True
            if last_seqword():
                return False

    return True  # complete pattern matched (I don't think we can ever hit this)


def check_verbs():
    """
    Primary coding loop which looks for verbs, checks whether any of their
    patterns match, then fills in the source and target if there has been a
    match. Stores events using make_event_strings().

    Note: the "upper" sequence is the part before the verb -- that is, higher
    on the screen -- and the "lower" sequence is the part after the verb.

    SourceLoc, TargetLoc structure

    [0]: the location in *Seq where the NE begins
    [1]: True - located in UpperSeq, otherwise in LowerSeq
    """
    global EventCode, SourceLoc, TargetLoc
    global IsPassive
    global ParseStart, ParseList

    def raise_CheckVerbs_error(kloc, call_location_string):
        """
        Handle problems found at some point internal to check_verbs: skip the
        verb that caused the problem but do skip the sentence. Logs the error
        and information on the verb phrase and raises CheckVerbsError.  This is
        currently only used for check_passive()
        """
        global SentenceID, ParseList
        warningstr = call_location_string + 'in check_verbs; verb sequence'
        '{} skipped: {}'.format(' '.join(ParseList[kloc:kloc + 5]),
                                SentenceID)
        logger = logging.getLogger('petr_log')
        logger.warning(warningstr)
        raise CheckVerbsError

    def check_passive(kitem):
        """
        Check whether the verb phrase beginning at kitem is passive; returns
        location of verb if true, zero otherwise.
        """
        try:
            cpendtag = ParseList.index('~' + ParseList[kitem][1:])
        except ValueError:
            raise_CheckVerbs_error(kitem, "check_passive()")
# no point in looking before + 3 since we need an auxiliary verb
        if '(VBN' in ParseList[kitem + 3:cpendtag]:
            ppvloc = ParseList.index('~VBN', kitem + 3)
            if 'BY' not in ParseList[ppvloc + 3:cpendtag]:
                return 0
            else:  # check for the auxiliary verb
                ka = ppvloc - 3
                while ka > kitem:
                    if '~VB' in ParseList[ka]:
                        if ParseList[ka - 1] in ['WAS', 'IS', 'BEEN', 'WAS']:
                            return (
                                # <14.04.30> replace this with a synset? Or a
                                # tuple? Or has the compiler done that anyway?
                                ppvloc - 1)
                    ka -= 1
                return 0
        else:
            return 0

    kitem = ParseStart
    while kitem < len(ParseList):
        if ('(VP' in ParseList[kitem]) and ('(VB' in ParseList[kitem + 1]):
            vpstart = kitem  # check_passive could change this
            try:
                pv = check_passive(kitem)
            except CheckVerbsError:
                kitem += 1
                continue
            IsPassive = (pv > 0)
            if IsPassive:
                kitem = pv - 2  # kitem + 2 is now at the passive verb
            targ = ParseList[kitem + 2] + ' '
            if ShowPattMatch:
                print("CV-0", targ)
            if targ in PETRglobals.VerbDict:
                SourceLoc = [-1, True]
                TargetLoc = [-1, True]
                if ShowPattMatch:
                    print("CV-1 Found", targ)
                endtag = '~' + ParseList[vpstart][1:]
                hasmatch = False
                if PETRglobals.VerbDict[targ][0]:
                    patternlist = PETRglobals.VerbDict[targ]
                    ka = 2
                    # check for multi-word.
                    while (ka < len(patternlist) and patternlist[ka][0]):
                        if ShowPattMatch:
                            print("CV/mult-1: Checking", targ, patternlist[ka])
                        if make_multi_sequences(patternlist[ka][2], kitem + 2,
                                                endtag):
                            if ShowPattMatch:
                                print("CV/mult-1: Found", targ, patternlist[ka])
                            verbcode = patternlist[ka][
                                0
                            ]  # save the default multi-word verb code
                            patternlist = PETRglobals.VerbDict[
                                patternlist[ka][1]
                            ]  # redirect to the list for the primary verb
                            break
                        ka += 1
                    else:
                        make_check_sequences(kitem + 2, endtag)
                        verbcode = patternlist[1]
                else:
                    patternlist = PETRglobals.VerbDict[
                        PETRglobals.VerbDict[targ][2]]
                    # redirect from a synonym
                    make_check_sequences(kitem + 2, endtag)
                    verbcode = PETRglobals.VerbDict[targ][1]
                kpat = 2
                if ShowPattMatch:
                    print("CV-2 patlist", patternlist)
                while kpat < len(patternlist):
                    SourceLoc = [-1, True]
                    TargetLoc = [-1, True]
                    if ShowPattMatch:
                        print("CV-2: Checking", targ, patternlist[kpat])
                    if verb_pattern_match(patternlist[kpat][0], UpperSeq, True):
                        if ShowPattMatch:
                            print("Found upper pattern match")
                        if verb_pattern_match(patternlist[kpat][1], LowerSeq,
                                              False):
                            if ShowPattMatch:
                                print("Found lower pattern match")  # debug
                            EventCode = patternlist[kpat][2]
                            hasmatch = True
                            break
                    kpat += 1
                if hasmatch and EventCode == '---':
                    hasmatch = False
                if not hasmatch and verbcode != '---':
                    if ShowPattMatch:
                        print("Matched on the primary verb")
#                       EventCode = PETRglobals.VerbDict[targ][1]
                    EventCode = verbcode
                    hasmatch = True

                if hasmatch:
                    if SourceLoc[0] < 0:
                        find_source()
                    if ShowPattMatch:
                        print("CV-3 src", SourceLoc)
                    if SourceLoc[0] >= 0:
                        if TargetLoc[0] < 0:
                            find_target()
                        if TargetLoc[0] >= 0:
                            if ShowPattMatch:
                                print("CV-3 tar", TargetLoc)
                            make_event_strings()

                if hasmatch:
                    while (endtag not in ParseList[kitem]):
                        kitem += 1  # resume search past the end of VP
        kitem += 1


def get_actor_code(index):
    """
    Get the actor code, resolving date restrictions.
    """
    global SentenceOrdDate

    logger = logging.getLogger('petr_log')

    thecode = None
    try:
        codelist = PETRglobals.ActorCodes[index]
    except IndexError:
        logger.warning(
            '\tError processing actor in get_actor_code. '
            'Index: {}'.format(index))
        thecode = '---'
    if len(codelist) == 1 and len(codelist[0]) == 1:
        thecode = codelist[0][0]  # no restrictions: the most common case
    for item in codelist:
        if len(item) > 1:  # interval date restriction
            if item[0] == 0 and SentenceOrdDate <= item[1]:
                thecode = item[2]
                break
            if item[0] == 1 and SentenceOrdDate >= item[1]:
                thecode = item[2]
                break
            if item[0] == 2 and SentenceOrdDate >= item[
                1
            ] and SentenceOrdDate <= item[2]:
                thecode = item[3]
                break
    # if interval search failed, look for an unrestricted code
    if not thecode:
        for item in codelist:  # assumes even if PETRglobals.WriteActorRoot,
            if len(item) == 1:  # the actor name at the end of the list will
                thecode = item[0]  # have length >1 if

    if not thecode:
        thecode = '---'
    elif PETRglobals.WriteActorRoot:
        thecode += PETRglobals.RootPrimer + codelist[-1]

    return thecode


def actor_phrase_match(patphrase, phrasefrag):
    """
    Determines whether the actor pattern patphrase occurs in phrasefrag. Returns
    True if match is successful.
    """

    #    APMprint = True
    APMprint = False
    connector = patphrase[1]
    kfrag = 1  # already know first word matched
    kpatword = 2  # skip code and connector
    if APMprint:
        print("APM-1", len(patphrase), patphrase, "\nAPM-2", len(phrasefrag),
              phrasefrag)
    if len(patphrase) == 2:
        if APMprint:
            print("APM-2.1: singleton match")
        return True  # root word is a sufficient match
    # <14.02.28>: these both do the same thing, except one handles a string of
    # the form XXX and the other XXX_. This is probably unnecessary. though it
    # might be...
    if len(patphrase) == 3 and patphrase[2][0] == "":
        if APMprint:
            print("APM-2.2: singleton match")  # debug
        return True  # root word is a sufficient match
    if kfrag >= len(phrasefrag):
        return False  # end of phrase with more to match
    while kpatword < len(patphrase):  # iterate over the words in the pattern
        if APMprint:
            # debug
            print("APM-3", kfrag, kpatword, "\n  APM Check:", kpatword,
                  phrasefrag[kfrag], patphrase[kpatword][0])
        if phrasefrag[kfrag] == patphrase[kpatword][0]:
            if APMprint:
                print("  APM match")  # debug
            connector = patphrase[kpatword][1]
            kfrag += 1
            kpatword += 1
            if kpatword >= len(patphrase) - 1:  # final element is terminator
                return True  # complete pattern matched
        else:
            if APMprint:
                print("  APM fail")
            if connector == '_':
                return False  # consecutive match required, so fail
            else:
                kfrag += 1  # intervening words are allowed
        if kfrag >= len(phrasefrag):
            return False  # end of phrase with more to match
    return True  # complete pattern matched (I don't think we can ever hit this)


def check_NEphrase(nephrase):
    """
    This function tries to find actor and agent patterns matching somewhere in
    the phrase.  The code for the first actor in the phrase is used as the
    base; there is no further search for actors

    All agents with distinct codes that are in the phrase are used -- including
    phrases which are subsets of other phrases (e.g. 'REBEL OPPOSITION GROUP
    [ROP]' and 'OPPOSITION GROUP' [OPP]) and they are appended in the order
    they are found. If an agent generates the same 3-character code (e.g.
    'PARLIAMENTARY OPPOSITION GROUP [OOP]' and 'OPPOSITION GROUP' [OPP]) the
    code is appended only the first time it is found.

    Note: In order to avoid accidental matches across codes, this checks in
    increments of 3 character blocks. That is, it assumes the CAMEO convention
    where actor and agent codes are usually 3 characters, occasionally 6 or 9,
    but always multiples of 3.

    If PETRglobals.WriteActorRoot is True, root phrase is added to the code
    following the string PETRglobals.RootPrimer
    """

    kword = 0
    actorcode = ""
    if ShowNEParsing:
        print("CNEPh initial phrase", nephrase)
    # iterate through the phrase looking for actors
    while kword < len(nephrase):
        phrasefrag = nephrase[kword:]
        if ShowNEParsing:
            print("CNEPh Actor Check", phrasefrag[0])
        # check whether patterns starting with this word exist in the dictionary
        if phrasefrag[0] in PETRglobals.ActorDict:
            if ShowNEParsing:
                print("                Found", phrasefrag[0])
            patlist = PETRglobals.ActorDict[nephrase[kword]]
            if ShowNEParsing:
                print("CNEPh Mk1:", patlist)
            # iterate over the patterns beginning with this word
            for index in range(len(patlist)):
                if actor_phrase_match(patlist[index], phrasefrag):
                    # found a coded actor
                    actorcode = get_actor_code(patlist[index][0])
                    if ShowNEParsing:
                        print("CNEPh Mk2:", actorcode)
                    break
        if len(actorcode) > 0:
            break  # stop after finding first actor
        else:
            kword += 1

    kword = 0
    agentlist = []
    while kword < len(nephrase):  # now look for agents
        phrasefrag = nephrase[kword:]
        if ShowNEParsing:
            print("CNEPh Agent Check", phrasefrag[0])
        # check whether patterns starting with this word exist in the
        # dictionary
        if phrasefrag[0] in PETRglobals.AgentDict:
            if ShowNEParsing:
                print("                Found", phrasefrag[0])
            patlist = PETRglobals.AgentDict[nephrase[kword]]
            # iterate over the patterns beginning with this word
            for index in range(len(patlist)):
                if actor_phrase_match(patlist[index], phrasefrag):
                    agentlist.append(patlist[index][0])  # found a coded actor
                    break
        kword += 1  # continue looking for more agents

    if len(agentlist) == 0:
        if len(actorcode) == 0:
            return [False]  # no actor or agent
        else:
            return [True, actorcode]  # actor only

    if len(actorcode) == 0:
        actorcode = '---'  # unassigned agent

    if PETRglobals.WriteActorRoot:
        part = actorcode.partition(PETRglobals.RootPrimer)
        actorcode = part[0]
        actorroot = part[2]

    for agentcode in agentlist:  # assemble the composite code
        if agentcode[0] == '~':
            agc = agentcode[1:]  # extract the code
        else:
            agc = agentcode[:-1]
        aglen = len(agc)  # set increment to the length of the agent code
        ka = 0  # check if the agent code is already present
        while ka < len(actorcode) - aglen + 1:
            if agc == actorcode[ka:ka + aglen]:
                ka = -1  # signal duplicate
                break
            ka += 3
        if ka < 0:
            break
        if agentcode[0] == '~':
            actorcode += agc
        else:
            actorcode = agc + actorcode
    if PETRglobals.WriteActorRoot:
        actorcode += PETRglobals.RootPrimer + actorroot

    return [True, actorcode]


def check_commas():
    """
    Removes comma-delimited clauses from ParseList.

    Note that the order here is to remove initial, remove terminal, then remove
    intermediate. Initial and terminal remove are done only once; the
    intermediate is iterated. In a sentence where the clauses can in fact be
    removed without affecting the structure, the result will still be balanced.
    If this is not the case, the routine raises a Skip_Record rather than
    continuing with whatever mess is left. Because this is working with
    ParseList, any commas inside (NP should already have had their tags removed
    as they were converted to (NE
    """

    def count_word(loclow, lochigh):
        """
        Returns the number of words in ParseList between loclow and lochigh - 1
        """
        cwkt = 0
        ka = loclow
        while ka < lochigh:
            if ParseList[ka] == '(NE':
                ka += 2  # skip over codes
            else:
                if ParseList[ka][0] != '(' and ParseList[ka][
                    0
                ] != '~' and ParseList[ka][0].isalpha():
                    cwkt += 1
                ka += 1
        return cwkt

    def find_end():
        """
        Returns location of tag on punctuation at end of phrase, defined as
        last element without ~
        """
        ka = len(ParseList) - 1
        while ka >= 2 and ParseList[ka][0] == '~':
            ka -= 1
        return ka - 1

    def delete_phrases(loclow, lochigh):
        """
        Deletes the complete phrases in ParseList between loclow and lochigh -
        1, leaving other mark-up. Ee go through this in reverse in order to use
        index(), as there is no rindex() for lists.
        """
        global ParseList  # 14.05.02: wtf is this needed??

        stack = []  # of course we use a stack...this is a tree...
        ka = lochigh - 1
        while ka >= loclow:
            if ParseList[ka][0] == '~':
                stack.append(ParseList[ka][1:])
# remove this complete phrase
            elif len(stack) > 0 and ParseList[ka][
                0
            ] == '(' and ParseList[ka][1:] == stack[-1]:
                targ = '~' + ParseList[ka][1:]
                ParseList = ParseList[:ka] + ParseList[ParseList.index(
                    targ, ka + 1) + 1:]
                # print 'pop:',stack,'\n',ParseList[loclow]
                stack.pop()
            ka -= 1

    global ParseList

    logger = logging.getLogger('petr_log')
    # displays trees at various points as ParseList is mangled
    ShowCCtrees = True
    ShowCCtrees = False

    if '(,' not in ParseList:
        return

    if ShowCCtrees:
        print('chkcomma-1-Parselist::', ParseList)
        show_tree_string(' '.join(ParseList))

    if PETRglobals.CommaBMax != 0:  # check for initial phrase
        """
        Initial phrase elimination in check_commas(): delete_phrases() will tend
        to leave a lot of (xx opening tags in place, making the tree a
        grammatical mess, which is why initial clause deletion is turned off by
        default.
        """

        kount = count_word(2, ParseList.index('(,'))

        if kount >= PETRglobals.CommaBMin and kount <= PETRglobals.CommaBMax:
            # leave the comma in place so an internal can catch it
            delete_phrases(2, ParseList.index('(,'))

        if ShowCCtrees:
            print('chkcomma-1a-Parselist::', ParseList)
            show_tree_string(' '.join(ParseList))

    if PETRglobals.CommaEMax != 0:  # check for terminal phrase
        kend = find_end()

        ka = kend - 1  # terminal: reverse search for '('
        while ka >= 2 and ParseList[ka] != '(,':
            ka -= 1
        if ParseList[ka] == '(,':
            kount = count_word(ka, len(ParseList))

            if (kount >= PETRglobals.CommaEMin and
                    kount <= PETRglobals.CommaEMax):
                # leave the comma in place so an internal can catch it
                delete_phrases(ka + 3, kend)

        if ShowCCtrees:
            print('chkcomma-2a-Parselist::')
            show_tree_string(' '.join(ParseList))
            print("cc-2t:", kount)

    if PETRglobals.CommaMax != 0:
        ka = ParseList.index('(,')
        while True:
            try:
                kb = ParseList.index('(,', ka + 1)
            except ValueError:
                break
            kount = count_word(ka + 2, kb)  # ka+2 skips over , ~,

            if kount >= PETRglobals.CommaMin and kount <= PETRglobals.CommaMax:
                delete_phrases(ka, kb)  # leave the second comma in place
            ka = kb

        if ShowCCtrees:
            print('chkcomma-3a-Parselist::')
            show_tree_string(' '.join(ParseList))

    # check for dangling initial or terminal (, , ~,
    ka = ParseList.index('(,')  # initial
    if count_word(2, ka) == 0:
        ParseList = ParseList[:ka] + ParseList[ka + 3:]

    kend = find_end()
    ka = kend - 1  # terminal: reverse search for '(,'
    while ka >= 2 and ParseList[ka] != '(,':
        ka -= 1
    if ParseList[ka] == '(,':
        if count_word(ka + 1, kend) == 0:
            ParseList = ParseList[:ka] + ParseList[ka + 3:]

    if ShowCCtrees:
        print('chkcomma-end-Parselist::')
        show_tree_string(' '.join(ParseList))

    try:
        check_balance()
    except UnbalancedTree:
        raise_ParseList_error('check_balance at end of check_comma()')


def assign_NEcodes():
    """
    Assigns non-null codes to NE phrases where appropriate.
    """

    def expand_compound_element(kstart):
        """
        An almost but not quite a recursive call on expand_compound_NEPhrase().
        This difference is that the (NEC has already been established so we are
        just adding elements inside the list and there is no further check.
        """
        global ParseList

        try:
            kend = ParseList.index('~NE', kstart)
            ncstart = ParseList.index('(NEC', kstart, kend)
            ncend = ParseList.index('~NEC', ncstart, kend)
        except ValueError:
            raise_ParseList_error('expand_compound_element() in assign_NEcodes')

        # first element is always '(NE'
        prelist = ParseList[kstart + 1:ncstart]
        postlist = ParseList[ncend + 1:kend]
        newlist = []
        ka = ncstart + 1
        while ka < ncend - 1:  # convert all of the NP, NNS and NNP to NE
            # any TreeBank (N* tag is legitimate here
            if '(N' in ParseList[ka]:
                endtag = '~' + ParseList[ka][1:]
                itemlist = ['(NE', '---']
                itemlist.extend(prelist)
                ka += 1
                while ParseList[ka] != endtag:
                    itemlist.append(ParseList[ka])
                    ka += 1
                itemlist.extend(postlist)
                itemlist.append('~NE')
                newlist.extend(itemlist)
            ka += 1  # okay to increment since next item is (, or (CC
        ParseList = ParseList[:kstart] + newlist + ParseList[kend + 1:]
        return kstart + len(newlist)

    def expand_compound_NEPhrase(kstart, kend):
        """
        Expand the compound phrases inside an (NE: this replaces these with a
        list of NEs with the remaining text simply duplicated. Code and agent
        resolution will then be done on these phrases as usual. This will
        handle two separate (NECs, which is as deep as one generally
        encounters.
        """
        global ParseList

        ncstart = ParseList.index('(NEC', kstart, kend)
        ncend = ParseList.index('~NEC', ncstart, kend)
        # first element is always '---'
        prelist = ParseList[kstart + 1:ncstart - 1]
        postlist = ParseList[ncend + 1:kend]
        newlist = ['(NEC']
        ka = ncstart + 1
        while ka < ncend - 1:  # convert all of the NP, NNS and NNP to NE
            if '(N' in ParseList[ka]:
                endtag = '~' + ParseList[ka][1:]
                itemlist = ['(NE', '---']
                itemlist.extend(prelist)
                ka += 1
                while ParseList[ka] != endtag:
                    itemlist.append(ParseList[ka])
                    ka += 1
                itemlist.extend(postlist)
                itemlist.append('~NE')
                newlist.extend(itemlist)
            ka += 1  # okay to increment since next item is (, or (CC
        newlist.append('~NEC')
        # insert a tell-tale here in case we need to further expand this
        newlist.append('~TLTL')
        ParseList = ParseList[:kstart] + newlist + ParseList[kend + 1:]
        if '(NEC' in newlist[1:-1]:  # expand next set of (NEC if it exists
            ka = kstart + 1
            while '(NE' in ParseList[ka:ParseList.index('~TLTL', ka)]:
                ka = expand_compound_element(ka)

        ParseList.remove('~TLTL')  # tell-tale is no longer needed

    global ParseStart, ParseList
    global nephrase

    kitem = ParseStart
    while kitem < len(ParseList):
        if '(NE' == ParseList[kitem]:
            if ShowNEParsing:
                print("NE-0:", kitem, ParseList[kitem - 1:])
            nephrase = []
            kstart = kitem
            kcode = kitem + 1
            kitem += 2  # skip NP, code,
            if kitem >= len(ParseList):
                raise_ParseList_error(
                    'Bounds overflow in (NE search in assign_NEcodes')

            while '~NE' != ParseList[kitem]:
                # <14.01.15> At present, read_TreeBank can leave (NNx in place
                # in situations involving (PP and (NEC: so COMPOUND-07. This is
                # a mildly kludgy workaround that insures a check_NEphrase gets
                # clean input
                if ParseList[kitem][1:3] != 'NN':
                    nephrase.append(ParseList[kitem])
                kitem += 1
                if kitem >= len(ParseList):
                    raise_ParseList_error(
                        'Bounds overflow in ~NE search in assign_NEcodes')

            if ShowNEParsing:
                print("aNEc", kcode, ":", nephrase)

            if '(NEC' in nephrase:
                expand_compound_NEPhrase(kstart, kitem)
                kitem = kstart - 1  # process the (NEs following the expansion
            else:
                result = check_NEphrase(nephrase)
                if result[0]:
                    ParseList[kcode] = result[1]
                    if ShowNEParsing:
                        print("Assigned", result[1])
        kitem += 1


def make_event_strings():
    """
    Creates the set of event strings, handing compound actors and symmetric
    events.
    """
    global SentenceLoc, SentenceID
    global EventCode, SourceLoc, TargetLoc
    global CodedEvents
    global IsPassive

    def extract_code_fields(fullcode):
        """
        Returns list containing actor code and optional root and text strings
        """
        if PETRglobals.CodePrimer in fullcode:
            maincode = fullcode[:fullcode.index(PETRglobals.CodePrimer)]
            rootstrg = None
            textstrg = None
            if PETRglobals.WriteActorRoot:
                part = fullcode.partition(PETRglobals.RootPrimer)
                if PETRglobals.WriteActorText:
                    rootstrg = part[2].partition(PETRglobals.TextPrimer)[0]
                else:
                    rootstrg = part[2]
            if PETRglobals.WriteActorText:
                textstrg = fullcode.partition(PETRglobals.TextPrimer)[2]
            return [maincode, rootstrg, textstrg]

        else:
            return [fullcode, None, None]

    def make_events(codessrc, codestar, codeevt):
        """
        Create events from each combination in the actor lists except
        self-references
        """
        global CodedEvents
        global SentenceLoc
        global IsPassive

        for thissrc in codessrc:
            if '(NEC' in thissrc:
                logger.warning(
                    '(NEC source code found in make_event_strings(): {}'.format(
                        SentenceID))
                CodedEvents = []
                return
            srclist = extract_code_fields(thissrc)

            if srclist[0][0:3] == '---' and len(SentenceLoc) > 0:
                srclist[0] = SentenceLoc + srclist[0][3:]
                # add location if known <14.09.24: this still hasn't been
                # implemented <>
            for thistar in codestar:
                if '(NEC' in thistar:
                    logger.warning(
                        '(NEC target code found in make_event_strings(): '
                        '{}'.format(SentenceID))
                    CodedEvents = []
                    return
                tarlist = extract_code_fields(thistar)
                if srclist[0] != tarlist[0]:
                    # skip self-references based on code
                    if tarlist[0][0:3] == '---' and len(SentenceLoc) > 0:
                        # add location if known -- see note above
                        tarlist[0] = SentenceLoc + tarlist[0][3:]
                    if IsPassive:
                        templist = srclist
                        srclist = tarlist
                        tarlist = templist
                    CodedEvents.append([srclist[0], tarlist[0], codeevt])
                    if PETRglobals.WriteActorRoot:
                        CodedEvents[-1].extend([srclist[1], tarlist[1]])
                    if PETRglobals.WriteActorText:
                        CodedEvents[-1].extend([srclist[2], tarlist[2]])

    def expand_compound_codes(codelist):
        """
        Expand coded compounds, that is, codes of the format XXX/YYY
        """
        for ka in range(len(codelist)):
            if '/' in codelist[ka]:
                parts = codelist[ka].split('/')
                # this will insert in order, which isn't necessary but might
                # be helpful
                kb = len(parts) - 2
                codelist[ka] = parts[kb + 1]
                while kb >= 0:
                    codelist.insert(ka, parts[kb])
                    kb -= 1

    logger = logging.getLogger('petr_log')
    srccodes = get_loccodes(SourceLoc)
    expand_compound_codes(srccodes)
    tarcodes = get_loccodes(TargetLoc)
    expand_compound_codes(tarcodes)

    # TODO: This needs to be fixed: this is the placeholder code for having a
    # general country- level location for the sentence or story
    SentenceLoc = ''

    if len(srccodes) == 0 or len(tarcodes) == 0:
        logger.warning(
            'Empty codes in make_event_strings(): {}'.format(SentenceID))
        return

    if ':' in EventCode:  # symmetric event
        if srccodes[0] == '---' or tarcodes[0] == '---':
            if tarcodes[0] == '---':
                tarcodes = srccodes
            else:
                srccodes = tarcodes
        ecodes = EventCode.partition(':')
        make_events(srccodes, tarcodes, ecodes[0])
        make_events(tarcodes, srccodes, ecodes[2])
    else:
        make_events(srccodes, tarcodes, EventCode)

    # remove null coded cases
    if PETRglobals.RequireDyad:
        ka = 0
        # need to evaluate the bound every time through the loop
        while ka < len(CodedEvents):
            if CodedEvents[ka][0] == '---' or CodedEvents[ka][1] == '---':
                del CodedEvents[ka]
            else:
                ka += 1
    if len(CodedEvents) == 0:
        return

    # remove duplicates
    ka = 0
    # need to evaluate the bound every time through the loop
    while ka < len(CodedEvents) - 1:
        kb = ka + 1
        while kb < len(CodedEvents):
            if CodedEvents[ka] == CodedEvents[kb]:
                del CodedEvents[kb]
            else:
                kb += 1
        ka += 1

    return

# ========================== PRIMARY CODING FUNCTIONS ====================== #


def reset_event_list(firstentry=False):
    """
    Set the event list and story globals for the current story or just
    intialize if firstentry probably should replace the magic numbers -6:-3
    here and in do_coding.
    """
    global SentenceDate, StoryDate, SentenceSource, StorySource
    global SentenceID, CurStoryID
    global StoryEventList, StoryIssues
    global NStory

    StoryEventList = []
    if PETRglobals.IssueFileName != "":
        StoryIssues = {}

    if firstentry:
        CurStoryID = ''
    else:
        CurStoryID = SentenceID[-6:-3]
        StoryDate = SentenceDate
        StorySource = SentenceSource
        NStory += 1


def extract_Sentence_info(item):
    """
    Extracts various global fields from the <Sentence record
    item is a dictionary of attributes generated from the XML input.
    """
    # can raise SkipRecord if date is missing

    global SentenceDate, SentenceID, SentenceCat, SentenceLoc, SentenceValid
    global SentenceOrdDate
    SentenceID = item['id']
    SentenceCat = item['category']
    if 'place' in item:
        SentenceLoc = item['place']
    else:
        SentenceLoc = ''
    if item['valid'].lower() == 'true':
        SentenceValid = True
    else:
        SentenceValid = False
    if 'date' in item:
        SentenceDate = item['date']
        SentenceOrdDate = PETRreader.dstr_to_ordate(SentenceDate)
    else:
        logger.warning(ErrMsgMissingDate)
        pass
        # raise SkipRecord


def check_discards():
    """
    Checks whether any of the discard phrases are in SentenceText, giving
    priority to the + matches. Returns [indic, match] where indic
       0 : no matches
       1 : simple match
       2 : story match [+ prefix]
    """
    global SentenceText

    sent = SentenceText.upper()  # case insensitive matching

    for target in PETRglobals.DiscardList:  # check all of the '+' cases first
        if target[0] == '+':
            mtarg = target[1:]
            if target[-1] == '_':
                mtarg = mtarg[:-1]
            loc = sent.find(mtarg)
            if loc >= 0:
                if target[-1] == '_':
                    if sent[loc + len(mtarg)] in ' .!?':
                        return [2, target]
                else:
                    return [2, target]

    for target in PETRglobals.DiscardList:
        if target[0] != '+':
            mtarg = target
            if target[-1] == '_':
                mtarg = mtarg[:-1]
            loc = sent.find(mtarg)
            if loc >= 0:
                if target[-1] == '_':
                    if sent[loc + len(mtarg)] in ' .!?':
                        return [1, target]
                else:
                    return [1, target]
    return [0, '']


def get_issues():
    """
    Finds the issues in SentenceText, returns as a list of [code,count]

    <14.02.28> stops coding and sets the issues to zero if it finds *any*
    ignore phrase
    """
    global SentenceText

    sent = SentenceText.upper()  # case insensitive matching
    issues = []

    for target in PETRglobals.IssueList:
        if target[0] in sent:  # found the issue phrase
            code = PETRglobals.IssueCodes[target[1]]
            if code[0] == '~':  # ignore code, so bail
                return []
            ka = 0
            gotcode = False
            while ka < len(issues):
                if code == issues[ka][0]:
                    issues[ka][1] += 1
                    break
                ka += 1
            if ka == len(issues):  # didn't find the code, so add it
                issues.append([code, 1])

    return issues


def code_record():
    """
    Code using ParseList read_TreeBank, then return results in StoryEventList
    first element of StoryEventList for each sentence -- this signals the start
    of a list events for a sentence -- followed by lists containing
    source/target/event triples.
    """
    global CodedEvents
    global ParseList
    global SentenceID
    global NEmpty

    # code triples that were produced; this is set in make_event_strings
    CodedEvents = []

    logger = logging.getLogger('petr_log')
    try:
        check_commas()
    except IndexError:
        raise_ParseList_error('Index error in check_commas()')

    try:
        assign_NEcodes()
    except NameError:
        print(SentenceOrdDate)
    if ShowParseList:
        print('code_rec-Parselist::', ParseList)

    try:
        check_verbs()  # can throw HasParseError which is caught in do_coding
    except IndexError:  # <14.09.04: HasParseError should get all of these now
        logger.warning(
            '\tIndexError in parsing, but HasParseError should have caught '
            'this. Probably a bad sentence.')
        print('\tIndexError in parsing. Probably a bad sentence.')

    if len(CodedEvents) > 0:
        return CodedEvents
    else:
        NEmpty += 1


def do_validation(filepath):
    """
    Unit tests using a validation file.
    """
    nvalid = 0

    tree = ET.parse(filepath)
    root = tree.getroot()

    open_validation_file(root)
    sents = root.find('Sentences')

    for item in sents:
        if item.tag == 'Config':
            change_Config_Options(item.attrib)
        if item.tag == 'Stop':
            print("Exiting: <Stop> record ")
            break
        if item.tag == 'Sentence':
            try:
                vresult = evaluate_validation_record(item)
                if vresult:
                    print("Events correctly coded in", SentenceID, '\n')
                    nvalid += 1
                else:
                    print("Error: Mismatched events in", SentenceID, '\n')
                    if ValidPause == 3:
                        sys.exit()

                if ValidPause == 2:
                    continue  # evaluate pause conditions
                elif ValidPause == 1 or not vresult:
                    inkey = input("Press <Return> to continue; 'q' to quit-->")
                    if 'q' in inkey or 'Q' in inkey:
                        break

            except EOFError:
                print("Exiting: end of file")
                PETRreader.close_FIN()
                print("Records coded correctly:", nvalid)
                sys.exit()
            except SkipRecord:
                print("Skipping this record.")
            except HasParseError:
                print("Exiting: parsing error ")
                PETRreader.close_FIN()
                sys.exit()

    PETRreader.close_FIN()
    print("Normal exit from validation\nRecords coded correctly:", nvalid)
    sys.exit()


def do_coding(event_dict, out_file):
    """
    Main coding loop Note that entering any character other than 'Enter' at the
    prompt will stop the program: this is deliberate.
    <14.02.28>: Bug: PETRglobals.PauseByStory actually pauses after the first
                sentence of the *next* story
    """
    global StoryDate, StorySource, SentenceID, SentenceCat, SentenceText
    global CurStoryID
    global NStory, NSent, NEvents, NDiscardSent, NDiscardStory, NEmpty
    global fevt
    global StoryIssues
    global CodedEvents

    # These are pulled from read_record()
    global SentenceDate, SentenceSource, SentenceOrdDate
    # Things to make local and global namespaces not conflict
    # TODO: Change this
    global treestr, ParseList

    NStory = 0
    NSent = 0
    NEvents = 0
    NEmpty = 0
    NDiscardSent = 0
    NDiscardStory = 0

    logger = logging.getLogger('petr_log')
    for key in event_dict:
        SkipStory = False
        logger.info('Processing {}'.format(key))
        print('Processing {}'.format(key))
        StoryDate = event_dict[key]['meta']['date']
        StorySource = 'TEMP'
        for sent in event_dict[key]['sents']:
            if 'parsed' in event_dict[key]['sents'][sent]:
                SentenceID = '{}_{}'.format(key, sent)
                logger.info('\tProcessing {}'.format(SentenceID))
                SentenceText = event_dict[key]['sents'][sent]['content']
                SentenceDate = StoryDate
                SentenceOrdDate = PETRreader.dstr_to_ordate(SentenceDate)
                SentenceSource = 'TEMP'

                parsed = event_dict[key]['sents'][sent]['parsed']
                treestr = parsed
                # TODO: Make read_TreeBank take treestr as an arg and return
                # something PAS <14.09.03>: yes, good idea: that global treestr
                # is left over from a much earlier version. Logically, it should
                # return ParseList
                try:
                    read_TreeBank()
                except IrregularPattern:
                    continue

                reset_event_list(True)

                # TODO Can implement this easily. The sentences are organized by
                # story in the dicts so it's easy to rework this. Just when
                # we're done with a key then write out the events for the
                # included sentences. Gonna skip it for now if not
                # PETRglobals.CodeBySentence: # write events when we hit a new
                # story if SentenceID[-6:-3] != CurStoryID: if not SkipStory:
                # write_events() reset_event_list() if PETRglobals.PauseByStory:
                # if len(raw_input("Press Enter to continue...")) > 0:
                # sys.exit() else: reset_event_list()

                disc = check_discards()
                if disc[0] > 0:
                    if disc[0] == 1:
                        print("Discard sentence:", disc[1])
                        logger.info('\tSentence discard. {}'.format(disc[1]))
                        NDiscardSent += 1
                        continue
                    else:
                        print("Discard story:", disc[1])
                        logger.info('\tStory discard. {}'.format(disc[1]))
                        SkipStory = True
                        NDiscardStory += 1
                        break

                    coded_events = None
                    # <14.09.16> Probably isn't needed now that discards t
                    # rigger either a continue or break

                else:
                    try:
                        coded_events = code_record()
                    except HasParseError:
                        coded_events = None

                if coded_events:
                    event_dict[key]['sents'][sent]['events'] = coded_events

                if coded_events and PETRglobals.IssueFileName != "":
                    event_issues = get_issues()
                    if event_issues:
                        event_dict[key]['sents'][sent]['issues'] = event_issues

                if PETRglobals.PauseBySentence:
                    if len(input("Press Enter to continue...")) > 0:
                        sys.exit()
            else:
                logger.info(
                    '{} has no parse information. Passing.'.format(SentenceID))
                pass

        if SkipStory:
            event_dict[key]['sents'] = None

    print("Summary:")
    print("Stories read:", NStory, "   Sentences coded:", NSent,
          "  Events generated:", NEvents)
    print("Discards:  Sentence", NDiscardSent, "  Story", NDiscardStory,
          "  Sentences without events:", NEmpty)

    return event_dict


def parse_cli_args():
    """Function to parse the command-line arguments for PETRARCH."""
    __description__ = """PETRARCH (https://openeventdata.github.io/) (v. 0.01)
    """
    aparse = argparse.ArgumentParser(prog='petrarch',
                                     description=__description__)

    sub_parse = aparse.add_subparsers(dest='command_name')
    parse_command = sub_parse.add_parser('parse',
                                         help="""Command to run the
                                         PETRARCH parser.""",
                                         description="""Command to run the
                                         PETRARCH parser.""")
    parse_command.add_argument('-i', '--inputs',
                               help='File, or directory of files, to parse.',
                               required=True)
    parse_command.add_argument('-P', '--parsed',
                               action='store_true',
                               default=False,
                               help="""Whether the input
                               document contains StanfordNLP-parsed text.""")
    parse_command.add_argument('-o', '--output',
                               help='File to write parsed events.',
                               required=True)
    parse_command.add_argument('-c', '--config',
                               help="""Filepath for the PETRARCH configuration
                               file. Defaults to PETR_config.ini""",
                               required=False)

    unittest_command = sub_parse.add_parser('validate',
                                            help="""Command to run
                                         the PETRARCH validation suite.""",
                                            description="""Command to run the
                                         PETRARCH validation suite.""")
    unittest_command.add_argument('-i', '--inputs',
                                  help="""Optional file that contains the
                               validation records. If not specified, defaults
                               to the built-in PETR.UnitTest.records.txt""",
                                  required=False)

    batch_command = sub_parse.add_parser('batch',
                                         help="""Command to run a batch
                                         process from parsed files specified by
                                         an optional config file.""",
                                         description="""Command to run a batch
                                         process from parsed files specified by
                                         an optional config file.""")
    batch_command.add_argument('-c', '--config',
                               help="""Filepath for the PETRARCH configuration
                               file. Defaults to PETR_config.ini""",
                               required=False)
    args = aparse.parse_args()
    return args


def main():
    cli_args = parse_cli_args()
    utilities.init_logger('PETRARCH.log')
    logger = logging.getLogger('petr_log')

    PETRglobals.RunTimeString = time.asctime()

    if cli_args.command_name == 'validate':
        PETRreader.parse_Config(utilities._get_data('data/config/',
                                                    'PETR_config.ini'))
        if not cli_args.inputs:
            validation_file = utilities._get_data('data/text',
                                                  'PETR.UnitTest.records.xml')
            do_validation(validation_file)
        else:
            do_validation(cli_args.inputs)

    if cli_args.command_name == 'parse' or cli_args.command_name == 'batch':
        start_time = time.time()

        if cli_args.config:
            print('Using user-specified config: {}'.format(cli_args.config))
            logger.info(
                'Using user-specified config: {}'.format(cli_args.config))
            PETRreader.parse_Config(cli_args.config)
        else:
            logger.info('Using default config file.')
            PETRreader.parse_Config(utilities._get_data('data/config/',
                                                        'PETR_config.ini'))

        read_dictionaries()

        print('\n\n')

        if cli_args.command_name == 'parse':
            if os.path.isdir(cli_args.inputs):
                if cli_args.inputs[-1] != '/':
                    paths = glob.glob(cli_args.inputs + '/*.xml')
                else:
                    paths = glob.glob(cli_args.inputs + '*.xml')
            elif os.path.isfile(cli_args.inputs):
                paths = [cli_args.inputs]
            else:
                print(
                    '\nFatal runtime error:\n"' + cli_args.inputs +
                    '" could not be located\nPlease enter a valid directory or '
                    'file of source texts.')
                sys.exit()

            run(paths, cli_args.output, cli_args.parsed)

        else:
            run(PETRglobals.TextFileList, PETRglobals.EventFileName, True)

        print("Coding time:", time.time() - start_time)

    print("Finished")


def read_dictionaries():
    print('Verb dictionary:', PETRglobals.VerbFileName)
    verb_path = utilities._get_data('data/dictionaries',
                                    PETRglobals.VerbFileName)
    PETRreader.read_verb_dictionary(verb_path)

    print('Actor dictionaries:', PETRglobals.ActorFileList)
    for actdict in PETRglobals.ActorFileList:
        actor_path = utilities._get_data('data/dictionaries', actdict)
        PETRreader.read_actor_dictionary(actor_path)

    print('Agent dictionary:', PETRglobals.AgentFileName)
    agent_path = utilities._get_data('data/dictionaries',
                                     PETRglobals.AgentFileName)
    PETRreader.read_agent_dictionary(agent_path)

    print('Discard dictionary:', PETRglobals.DiscardFileName)
    discard_path = utilities._get_data('data/dictionaries',
                                       PETRglobals.DiscardFileName)
    PETRreader.read_discard_list(discard_path)

    if PETRglobals.IssueFileName != "":
        print('Issues dictionary:', PETRglobals.IssueFileName)
        issue_path = utilities._get_data('data/dictionaries',
                                         PETRglobals.IssueFileName)
        PETRreader.read_issue_list(issue_path)


def run(filepaths, out_file, s_parsed):
    events = PETRreader.read_xml_input(filepaths, s_parsed)
    if not s_parsed:
        events = utilities.stanford_parse(events)
    updated_events = do_coding(events, 'TEMP')
    PETRwriter.write_events(updated_events, out_file)


def run_pipeline(data,
                 out_file=None,
                 config=None,
                 write_output=True,
                 parsed=False):
    utilities.init_logger('PETRARCH.log')
    logger = logging.getLogger('petr_log')
    if config:
        print('Using user-specified config: {}'.format(config))
        logger.info('Using user-specified config: {}'.format(config))
        PETRreader.parse_Config(config)
    else:
        logger.info('Using default config file.')
        logger.info('Config path: {}'.format(
            utilities._get_data('data/config/', 'PETR_config.ini')))
        PETRreader.parse_Config(utilities._get_data('data/config/',
                                                    'PETR_config.ini'))

    read_dictionaries()

    logger.info('Hitting read events...')
    events = PETRreader.read_pipeline_input(data)
    if parsed:
        logger.info('Hitting do_coding')
        updated_events = do_coding(events, 'TEMP')
    else:
        events = utilities.stanford_parse(events)
        updated_events = do_coding(events, 'TEMP')
    if not write_output:
        output_events = PETRwriter.pipe_output(updated_events)
        return output_events
    elif write_output and not out_file:
        print('Please specify an output file...')
        logger.warning('Need an output file. ¯\_(ツ)_/¯')
        sys.exit()
    elif write_output and out_file:
        PETRwriter.write_events(updated_events, out_file)


if __name__ == '__main__':
    main()
