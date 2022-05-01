"""

BASEBALL GAME THREAD BOT

Written by:
KimbaWLion

Please contact us on Github if you have any questions.

"""

import statsapi
from datetime import datetime, timedelta
import pytz
import asyncio
import discord
import json
import BaseballConsumerConstants as constants
from TeamAndStandingsUtilities import get_division_for_teamId
import assets

SETTINGS_FILE = './settings.json'


class BaseballUpdaterBotV2:

    async def run(self, client, channel):
        error_msg = self.read_settings()
        if error_msg != 0:
            print(error_msg)
            return

        print('in BaseballUpdaterBotV2.run()')

        while True:
            idsOfPrevEvents = self.getEventIdsFromLog()
            todaysGame = (datetime.now() - timedelta(hours=5)).strftime("%m/%d/%Y")
            how_long_to_wait_in_sec = 300

            sched = statsapi.get("schedule", {'sportId': 1, "teamId": self.TEAM_ID, "date": todaysGame, "hydrate": "leagueRecord,decisions,probablePitcher(note),linescore"})

            if not sched['dates']:
                noGameId = ''.join(["NoGameToday", todaysGame])
                if noGameId not in idsOfPrevEvents:
                    await self.postNoGameStatusOnDiscord(channel)
                    self.printNoGameToLog(noGameId)
                print("[{}] No game today".format(self.getTime()))
                how_long_to_wait_in_sec = 1000

            else:
                for game in sched['dates'][0]['games']:
                    # Get team names
                    homeTeamInfo = self.lookupTeamInfo(game['teams']['home']['team']['id'])
                    awayTeamInfo = self.lookupTeamInfo(game['teams']['away']['team']['id'])
                    # Add current game score
                    # Note, linescore isn't always populated :(
                    try: homeTeamInfo['game_score'] = game['linescore']['teams']['home']['runs']
                    except KeyError: homeTeamInfo['game_score'] = 0
                    try: awayTeamInfo['game_score'] = game['linescore']['teams']['away']['runs']
                    except KeyError: awayTeamInfo['game_score'] = 0

                    # Add team records
                    homeTeamInfo['wins'] = game['teams']['home']['leagueRecord']['wins']
                    homeTeamInfo['losses'] = game['teams']['home']['leagueRecord']['losses']
                    awayTeamInfo['wins'] = game['teams']['away']['leagueRecord']['wins']
                    awayTeamInfo['losses'] = game['teams']['away']['leagueRecord']['losses']
                    # Add pitcher data
                    homeTeamInfo['probable_pitcher_name'] = game['teams']['home']['probablePitcher']['fullName'] if 'probablePitcher' in game['teams']['home'] else ''
                    homeTeamInfo['probable_pitcher_id'] = game['teams']['home']['probablePitcher']['id'] if 'probablePitcher' in game['teams']['home'] else ''
                    awayTeamInfo['probable_pitcher_name'] = game['teams']['away']['probablePitcher']['fullName'] if 'probablePitcher' in game['teams']['away'] else ''
                    awayTeamInfo['probable_pitcher_id'] = game['teams']['away']['probablePitcher']['id'] if 'probablePitcher' in game['teams']['away'] else ''

                    # First, check if the game status has changed
                    gameStatus = game['status']['detailedState']
                    gameStatusWaitTime = how_long_to_wait_in_sec # default wait of 300 sec
                    gameStatusId = ''.join([gameStatus.replace(" ", ""), ';', str(game['gamePk']), todaysGame])
                    if gameStatusId not in idsOfPrevEvents:
                        await self.postGameStatusOnDiscord(channel, gameStatus, awayTeamInfo, homeTeamInfo, todaysGame, game['gameDate'])
                        self.printStatusToLog(gameStatusId, gameStatus)
                    print("[{}] Game is {}".format(self.getTime(), gameStatus))

                    # Change the update period based on the gameStatus
                    if gameStatus == 'Scheduled':
                        gameStatusWaitTime = 300
                    if gameStatus == 'Pre-Game':
                        gameStatusWaitTime = 60
                    if gameStatus == 'Warmup':
                        gameStatusWaitTime = 60
                    if "Delayed Start" in gameStatus:
                        gameStatusWaitTime = 300
                    if gameStatus == 'In Progress':
                        gameStatusWaitTime = 10
                    if 'Manager challenge' in gameStatus:
                        gameStatusWaitTime = 10
                    if gameStatus == 'Postponed':
                        gameStatusWaitTime = 300
                    if 'Game Over' in gameStatus:
                        gameStatusWaitTime = 60
                    if 'Final' in gameStatus:
                        gameStatusWaitTime = 300
                    if gameStatus == 'Delayed: Rain':
                        gameStatusWaitTime = 300
                    if gameStatus == 'Completed Early: Rain':
                        gameStatusWaitTime = 300

                    # If game is a doubleheader, if the 2nd game has a longer wait time than the first, use the first's wait time
                    gameIsDoubleHeader = game['doubleHeader'] != "N" or len(sched['dates'][0]['games']) > 1  # Suspended games being restarted with a 2nd game that day do not count as doubleheaders
                    how_long_to_wait_in_sec = gameStatusWaitTime if not gameIsDoubleHeader else (how_long_to_wait_in_sec if how_long_to_wait_in_sec < gameStatusWaitTime else gameStatusWaitTime)

                    # If game is currently active, search for plays to post
                    if gameStatus == 'In Progress' or 'Manager challenge' in gameStatus or 'Game Over' in gameStatus:
                        # Game Event logic
                        gameInfo = statsapi.get('game', {'gamePk': game['gamePk']})
                        liveData = gameInfo['liveData']
                        plays = liveData['plays']['allPlays']
                        linescore = liveData['linescore']
                        fullLinescoreString = statsapi.linescore(game['gamePk'])
                        strikeoutTracker = {'home': [], 'away': []} # Boolean list, true = swinging, false = looking

                        for play in plays:
                            # If the item is not full yet (as in the atbat is finished) skip
                            if not 'description' in play['result'].keys():
                                continue

                            # Get info from plays
                            info = {}
                            info['homeTeamFullName'] = homeTeamInfo['name']
                            info['homeTeamName'] = homeTeamInfo['teamName']
                            info['homeTeamShortFullName'] = homeTeamInfo['shortName']
                            info['homeTeamAbbv'] = homeTeamInfo['fileCode']
                            info['homeTeamId'] = homeTeamInfo['id']
                            info['awayTeamFullName'] = awayTeamInfo['name']
                            info['awayTeamName'] = awayTeamInfo['teamName']
                            info['awayTeamShortFullName'] = awayTeamInfo['shortName']
                            info['awayTeamAbbv'] = awayTeamInfo['fileCode']
                            info['awayTeamId'] = awayTeamInfo['id']
                            info['startTime'] = play['about']['startTime']
                            info['inning'] = str(play['about']['inning'])
                            info['inningHalf'] = play['about']['halfInning']
                            info['balls'] = str(play['count']['balls'])
                            info['strikes'] = str(play['count']['strikes'])
                            info['outs'] = str(play['count']['outs'])
                            info['homeScore'] = str(play['result']['homeScore'])
                            info['awayScore'] = str(play['result']['awayScore'])
                            info['description'] = play['result']['description']
                            info['event'] = play['result']['event']
                            info['rbi'] = play['result']['rbi']
                            info['playType'] = play['result']['type']
                            info['manOnFirst'] = True if 'postOnFirst' in play['matchup'] else False
                            info['manOnSecond'] = True if 'postOnSecond' in play['matchup'] else False
                            info['manOnThird'] = True if 'postOnThird' in play['matchup'] else False
                            info['runsScored'] = 0
                            info['rbis'] = 0
                            info['runsEarned'] = 0
                            for runner in play['runners']:
                                info['runsScored'] += 1 if runner['details']['isScoringEvent'] else 0
                                info['rbis'] += 1 if runner['details']['rbi'] else 0
                                info['runsEarned'] += 1 if runner['details']['earned'] else 0

                            # Get info from linescore
                            info['outs_linescore'] = linescore['outs']
                            info['homeStats_linescore'] = linescore['teams']['home'] #runs, hits, errors, lefOnBase
                            info['awayStats_linescore'] = linescore['teams']['away']
                            info['currentInning_linescore'] = linescore['currentInning']
                            info['inningState_linescore'] = linescore['inningState'] # Middle or End
                            info['inningHalf_linescore'] = linescore['inningHalf']

                            # Get full linescore summary
                            info['fullLinescoreString'] = fullLinescoreString

                            # playType isn't working, do it yourself
                            info['playTypeActual'] = self.getPlayType(info['description'])
                            info['batter'] = play['matchup']['batter']
                            info['pitcher'] = play['matchup']['pitcher']
                            info['balls'] = play['count']['balls']
                            info['strikes'] = play['count']['strikes']
                            info['play_events'] = play['playEvents']

                            # Update strikeout tracker
                            if info['event'] == 'Strikeout':
                                if self.homeTeamBatting(info):
                                    currentStrikeouts = strikeoutTracker['away']
                                    if "strikes out" in info['description']:
                                        currentStrikeouts.append(True)
                                    if "called out on strikes" in info['description']:
                                        currentStrikeouts.append(False)
                                    strikeoutTracker['away'] = currentStrikeouts
                                else:
                                    currentStrikeouts = strikeoutTracker['home']
                                    if "strikes out" in info['description']:
                                        currentStrikeouts.append(True)
                                    if "called out on strikes" in info['description']:
                                        currentStrikeouts.append(False)
                                    strikeoutTracker['home'] = currentStrikeouts
                            info['strikeoutTracker'] = strikeoutTracker

                            # Generate ID unique for each play
                            info['id'] = ''.join([info['startTime'].split(":")[0],';',info['outs'],';',info['inning'],';',info['homeScore'],';',info['awayScore'],';',info['description'].replace(" ", "")])

                            # if ID is not in log, add it to log and then post update on Discord
                            if info['id'] not in idsOfPrevEvents:
                                self.printToLog(info)
                                temp = self.commentOnDiscordEvent(info)
                                if type(temp) == discord.Embed:
                                    await channel.send(embed=temp)
                                else:
                                    await channel.send(temp)

            await asyncio.sleep(how_long_to_wait_in_sec)

        # Should never reach here
        print("/*------------- End of Bot.run() -------------*/")

    def read_settings(self):
        with open(SETTINGS_FILE) as data:
            settings = json.load(data)

            self.GAME_THREAD_LOG = settings.get('GAME_THREAD_LOG')
            if self.GAME_THREAD_LOG == None: return "Missing GAME_THREAD_LOG"

            self.TEAM_ID = settings.get('TEAM_ID')
            if self.TEAM_ID == None: return "Missing TEAM_ID"

        return 0

    def getTime(self):
        today = datetime.today().strftime("%Y/%m/%d %H:%M:%S")
        return today

    def printToLog(self, info):
        with open(self.GAME_THREAD_LOG, "a") as log:
            log.write("[{}] [{}] | {}\n".format(self.getTime(), info['id'], info['description']))
        log.close()
        print("[{}] New atBat: {}".format(self.getTime(), info['description']))

    def printStatusToLog(self, statusId, status):
        with open(self.GAME_THREAD_LOG, "a") as log:
            log.write("[{}] [{}] | {}\n".format(self.getTime(), statusId, status))
        log.close()
        print("[{}] New status: {}".format(self.getTime(), statusId))

    def printNoGameToLog(self, noGameId):
        self.printStatusToLog(noGameId, "No Game Today")

    def getEventIdsFromLog(self):
        idsFromLog = []
        with open(self.GAME_THREAD_LOG) as log:
            for line in log:
                splitLine = line.split(" ")
                id = splitLine[2][1:-1]
                idsFromLog.append(id)
        log.close()
        return idsFromLog

    def getPlayType(self, description):
        if "Status Change" in description: return "statusChange"
        if "Mound Visit" in description: return "moundVisit"
        if "Pitching Change" in description: return "pitchingChange"
        if "Defensive Substitution" in description: return "defensiveSubstitution"
        if "Offensive Substitution" in description: return "offensiveSubstitution"
        if "remains in the game" in description: return "remainsInTheGame"
        if "Game Advisory" in description: return "gameAdvisory"
        if "Umpire Substitution" in description: return "umpireSubstitution"
        if "Injury Delay" in description: return "injuryDelay"
        if "left the game" in description: return "leftTheGame"
        if "ejected" in description: return "ejected"
        return 'atBat'

    async def postNoGameStatusOnDiscord(self, channel):
        gameStatusEmbed = discord.Embed(title=constants.NO_GAME_STATUS_TITLE,
                                        description=constants.NO_GAME_STATUS_DESCRIPTION)
        gameStatusPost = constants.NO_GAME_STATUS_BODY
        await channel.send(embed=gameStatusEmbed)
        if gameStatusPost:
            await channel.send(gameStatusPost)

    async def postGameStatusOnDiscord(self, channel, gameStatus, awayTeamInfo, homeTeamInfo, todaysGame, gameDateTime):
        gameStatusEmbed = discord.Embed(title="Game status {} has no current post content".format(gameStatus),
                                              description="Game status {} has no current post content".format(gameStatus))
        gameStatusPost = "Game status {} has no current post content".format(gameStatus)

        # Different embeds and posts for each status
        if gameStatus == 'Scheduled':
            gameStart = pytz.utc.localize(datetime.strptime(gameDateTime, '%Y-%m-%dT%H:%M:%SZ'))
            localizedGameStart = gameStart.astimezone(pytz.timezone(constants.BOT_TIMEZONE)).strftime("%I:%M %p")

            gameStatusEmbed = discord.Embed(title=constants.SCHEDULED_GAME_STATUS_TITLE,
                                            description="The {} ({}-{}) play @ {} ({}-{}) today at {} {}".format(
                                                awayTeamInfo['teamName'], awayTeamInfo['wins'], awayTeamInfo['losses'],
                                                homeTeamInfo['teamName'], homeTeamInfo['wins'], homeTeamInfo['losses'],
                                                localizedGameStart, constants.BOT_TIMEZONE))
            gameStatusPost = constants.SCHEDULED_GAME_STATUS_BODY

        if gameStatus == 'Pre-Game':
            gameStatusEmbed = discord.Embed(title=constants.PREGAME_TITLE, description=constants.PREGAME_DESCRIPTION)
            gameStatusPost = constants.PREGAME_BODY

        if gameStatus == 'Warmup':
            nullPitcherData = {'wins': '---', 'losses': '---', 'era': '---'} # This is if the pitcher was just called up and aren't in MLB.com's system yet
            awayStartingPitcher = statsapi.player_stat_data(awayTeamInfo['probable_pitcher_id'], group="pitching", type="season")
            homeStartingPitcher = statsapi.player_stat_data(homeTeamInfo['probable_pitcher_id'], group="pitching", type="season")
            awayStartingPitcherData = awayStartingPitcher['stats'][0]['stats'] if awayStartingPitcher['stats'] else nullPitcherData
            homeStartingPitcherData = homeStartingPitcher['stats'][0]['stats'] if homeStartingPitcher['stats'] else nullPitcherData

            pregamePost = "{} Pitcher: {} ({}-{} {})\n" \
                          "{} Pitcher: {} ({}-{} {})".format(
                awayTeamInfo['teamName'],
                awayTeamInfo['probable_pitcher_name'], awayStartingPitcherData['wins'],
                awayStartingPitcherData['losses'], awayStartingPitcherData['era'],
                homeTeamInfo['teamName'],
                homeTeamInfo['probable_pitcher_name'], homeStartingPitcherData['wins'],
                homeStartingPitcherData['losses'], homeStartingPitcherData['era'])

            gameStatusEmbed = discord.Embed(title=constants.WARMUP_TITLE, description=pregamePost)
            gameStatusPost = constants.WARMUP_BODY

        if "Delayed Start" in gameStatus:
            gameStatusEmbed = discord.Embed(title=constants.DELAYEDSTART_TITLE, description=constants.DELAYEDSTART_DESCRIPTION)
            gameStatusPost = constants.DELAYEDSTART_BODY

        # Specifically for Game Started (only goes first time game becomes "In Progress"
        if gameStatus == 'In Progress':
            gameStatusEmbed = discord.Embed(title=constants.GAMESTARTED_TITLE, description=constants.GAMESTARTED_DESCRIPTION)
            gameStatusPost = constants.GAMESTARTED_BODY

        if gameStatus == 'Delayed: Rain':
            gameStatusEmbed = discord.Embed(title=constants.RAINDELAY_TITLE, description=constants.RAINDELAY_DESCRIPTION)
            gameStatusPost = constants.RAINDELAY_BODY

        if gameStatus == 'Suspended: Rain':
            gameStatusEmbed = discord.Embed(title=constants.SUSPENDEDRAIN_TITLE, description=constants.SUSPENDEDRAIN_DESCRIPTION)
            gameStatusPost = constants.SUSPENDEDRAIN_BODY

        if gameStatus == 'Completed Early: Rain':
            gameStatusEmbed = discord.Embed(title=constants.COMPLETEDEARLYRAIN_TITLE, description=constants.COMPLETEDEARLYRAIN_DESCRIPTION)
            gameStatusPost = constants.COMPLETEDEARLYRAIN_BODY

        if gameStatus == 'Postponed':
            gameStatusEmbed = discord.Embed(title=constants.POSTPONED_TITLE.format(todaysGame), description=constants.POSTPONED_DESCRIPTION)
            gameStatusPost = constants.POSTPONED_BODY

        if gameStatus == 'Game Over':
            endOfGameAnnouncement = self.formatEndOfGameAnnouncement(awayTeamInfo, homeTeamInfo)
            if (self.favoriteTeamWon(awayTeamInfo, homeTeamInfo)):
                gameStatusEmbed = discord.Embed(title=constants.GAMEOVER_WIN_TITLE, description=endOfGameAnnouncement)
                gameStatusPost = constants.GAMEOVER_WIN_BODY
            else:
                gameStatusEmbed = discord.Embed(title=constants.GAMEOVER_LOSS_TITLE, description=endOfGameAnnouncement)
                gameStatusPost = constants.GAMEOVER_LOSS_BODY

        if gameStatus == 'Final':
            gameStatusEmbed = discord.Embed(title=constants.FINAL_TITLE,
                                            description='```{}```'.format(statsapi.standings(date=todaysGame, include_wildcard=False, division=get_division_for_teamId(self.TEAM_ID))))
            gameStatusPost = constants.FINAL_BODY

        if gameStatus == 'Game Over: Tied':
            gameStatusEmbed = discord.Embed(title=constants.GAMEOVERTIED_TITLE, description=constants.GAMEOVERTIED_DESCRIPTION)
            gameStatusPost = constants.GAMEOVERTIED_BODY

        if gameStatus == 'Final: Tied':
            gameStatusEmbed = discord.Embed(title=constants.FINALTIED_TITLE, description=constants.FINALTIED_DESCRIPTION)
            gameStatusPost = constants.FINALTIED_BODY

        if 'Manager challenge' in gameStatus:
            gameStatusEmbed = discord.Embed(title=constants.MANAGER_CHALLENGE_TITLE, description=constants.MANAGER_CHALLENGE_DESCRIPTION)
            gameStatusPost = constants.MANAGER_CHALLENGE_BODY

        await channel.send(embed=gameStatusEmbed)
        if gameStatusPost:
            await channel.send(gameStatusPost)

    def commentOnDiscordEvent(self, info):
        if info['playTypeActual'] == 'atBat':
            comment = self.formatGameEventForDiscord(info)
        else:
            comment = self.formatPlayerChangeForDiscord(info)
        return comment

    def formatGameEventForDiscord(self, info):
        if info['inningHalf'] == 'bottom':
            embed_color = discord.Color(value=int(assets.team_colors[info['homeTeamAbbv'].upper()], 16))
            embed_icon = assets.team_logos[info['homeTeamAbbv'].upper()]
        else:
            embed_color = discord.Color(value=int(assets.team_colors[info['awayTeamAbbv'].upper()], 16))
            embed_icon = assets.team_logos[info['awayTeamAbbv'].upper()]

        title = f"{info['awayTeamName']} @ {info['homeTeamName']} {datetime.today().month}/{datetime.today().day}/{datetime.today().year}"
        description = f"{info['inningHalf'].title()} {info['inning']} - {info['outs']} out(s)\n"
        description += f"{info['batter']['fullName']} batting against {info['pitcher']['fullName']}\n\n"
        description += f"{info['description']}\n\n"
        description += f"{info['awayTeamAbbv'].upper()} {info['awayStats_linescore']['runs']} - {info['homeTeamAbbv'].upper()} {info['homeStats_linescore']['runs']}"

        embed = discord.Embed(description=description, color=embed_color)
        embed.set_author(name=title, icon_url=embed_icon)
        embed.set_thumbnail(url=assets.obc_img[f"{int(info['manOnFirst'])}{int(info['manOnSecond'])}{int(info['manOnThird'])}"])
        plays = '```'
        for event in info['play_events']:
            if event['isPitch']:
                plays += f"{event['count']['balls']}-{event['count']['strikes']} {event['details']['description']} {event['pitchData']['startSpeed']} {event['details']['type']['description']}\n"
        plays += '```'
        embed.add_field(name='Plays', value=plays)
        return embed

        return "```" \
               "{}\n" \
               "{}{}\n" \
               "```\n" \
               "{}" \
               "{}".format(self.formatLinescoreForDiscord(info)
                                          if not self.gameEventInningBeforeCurrentLinescoreInning(info)
                                          else self.formatLinescoreCatchingUpForDiscord(info),
                           self.formatPitchCount(info), info['description'],
                           self.funEmoji(info),
                           self.endOfInning(info))

    def formatLinescoreForDiscord(self, info):
        return "{}   ┌───┬──┬──┬──┐\n" \
               "   {}     │{:<3}│{:>2}│{:>2}│{:>2}│\n" \
               "  {} {}    ├───┼──┼──┼──┤\n" \
               "{}   │{:<3}│{:>2}│{:>2}│{:>2}│\n" \
               "         └───┴──┴──┴──┘".format(
            self.formatInning(info),
            self.formatSecondBase(info['manOnSecond']),
            info['awayTeamAbbv'].upper(), info['awayStats_linescore']['runs'],info['awayStats_linescore']['hits'], info['awayStats_linescore']['errors'],
            self.formatThirdBase(info['manOnThird']), self.formatFirstBase(info['manOnFirst']),
            self.formatOuts(info['outs']),
            info['homeTeamAbbv'].upper(), info['homeStats_linescore']['runs'],info['homeStats_linescore']['hits'], info['homeStats_linescore']['errors']
        )

    def gameEventInningBeforeCurrentLinescoreInning(self, info):
        return True if int(info['inning']) < int(info['currentInning_linescore']) else False

    def formatLinescoreCatchingUpForDiscord(self, info):
        return "{}\n" \
               "\n" \
               "  BOT         CATCHING\n" \
               " BEHIND          UP\n" \
               "".format(
            self.formatInning(info)
        )

    def formatInning(self, info):
        return "{} {:>2}".format(info['inningHalf'].upper()[0:3], info['inning'])

    def formatOuts(self, outs):
        outOrOuts = " Outs"
        if outs == "1": outOrOuts = "  Out"
        return "".join([outs, outOrOuts])

    def formatFirstBase(self, runnerOnBaseStatus):
        return self.formatBase(runnerOnBaseStatus)

    def formatSecondBase(self, runnerOnBaseStatus):
        return self.formatBase(runnerOnBaseStatus)

    def formatThirdBase(self, runnerOnBaseStatus):
        return self.formatBase(runnerOnBaseStatus)

    def formatBase(self, baseOccupied):
        if baseOccupied:
            return "●"
        return "○"

    def formatPitchCount(self, info):
        if info['playType'] == 'atBat': return "On a {}-{} count, ".format(info['balls'], info['strikes'])
        else: return ""

    def endOfInning(self, info):
        if info['outs'] == "3":
            endOfInningString = "```------ End of {} ------\n{}\n------ End of {} ------```".format(self.formatInning(info), info['fullLinescoreString'], self.formatInning(info))
            if info['inning'] == "7" and info['inningHalf'].upper()[0:3] == "TOP":
                endOfInningString = "{}\n{}".format(endOfInningString, constants.SEVENTH_INNING_STRETCH)
            return endOfInningString
        return ""

    def formatPlayerChangeForDiscord(self, info):
        return "```" \
               "{}\n" \
               "```\n" \
               "{}".format(info['description'],
                           self.endOfInning(info))

    def lookupTeamInfo(self, id):
        teamInfoList = statsapi.lookup_team(id)
        if len(teamInfoList) != 1:
            print("Team id", id, "cannot be resolved to a single team")
            return
        return teamInfoList[0]

    def homeTeamBatting(self, info):
        return info['inningHalf'].upper()[0:3] == "BOT"

    def funEmoji(self, info):
        emoji = ""

        ## Pitching emoji
        if info['strikes'] == '3':
            if self.homeTeamBatting(info):
                emoji = "{} K Tracker ({}): ".format(info['awayTeamName'], len(info['strikeoutTracker']['away']))
                if info['strikeoutTracker']['away'] == [True, True, True]: # If KKK, make "3 Ks"
                    emoji = ''.join([emoji, '3 ', constants.EMOTE_STRIKEOUT if self.checkIfFavoriteTeam(info['awayTeamId']) else constants.EMOTE_OTHER_TEAM_STRIKEOUT, 's'])
                else:
                    for swingingStrikeout in info['strikeoutTracker']['away']:
                        if swingingStrikeout: emoji = ''.join([emoji, constants.EMOTE_STRIKEOUT         if self.checkIfFavoriteTeam(info['awayTeamId']) else constants.EMOTE_OTHER_TEAM_STRIKEOUT])
                        else:                 emoji = ''.join([emoji, constants.EMOTE_STRIKEOUT_LOOKING if self.checkIfFavoriteTeam(info['awayTeamId']) else constants.EMOTE_OTHER_TEAM_STRIKEOUT_LOOKING])
            else:
                emoji = "{} K Tracker ({}): ".format(info['homeTeamName'], len(info['strikeoutTracker']['home']))
                if info['strikeoutTracker']['home'] == [True, True, True]: # If KKK, make "3 Ks"
                    emoji = ''.join([emoji, '3 ', constants.EMOTE_STRIKEOUT if self.checkIfFavoriteTeam(info['homeTeamId']) else constants.EMOTE_OTHER_TEAM_STRIKEOUT, 's'])
                else:
                    for swingingStrikeout in info['strikeoutTracker']['home']:
                        if swingingStrikeout: emoji = ''.join([emoji, constants.EMOTE_STRIKEOUT         if self.checkIfFavoriteTeam(info['homeTeamId']) else constants.EMOTE_OTHER_TEAM_STRIKEOUT])
                        else:                 emoji = ''.join([emoji, constants.EMOTE_STRIKEOUT_LOOKING if self.checkIfFavoriteTeam(info['homeTeamId']) else constants.EMOTE_OTHER_TEAM_STRIKEOUT_LOOKING])
            emoji = ''.join([emoji, '\n'])

        ## Batting emoji
        favTeamIsBatting = (self.checkIfFavoriteTeam(info['homeTeamId']) and self.homeTeamBatting(info)) or (self.checkIfFavoriteTeam(info['awayTeamId']) and not self.homeTeamBatting(info))
        # Grand Slam
        if info['event'] == 'Home Run' and info['rbi'] == 4: # "grand slam" in info['description']:
            emoji = ''.join([emoji, constants.EMOTE_GRAND_SLAM if favTeamIsBatting else constants.EMOTE_OTHER_TEAM_GRAND_SLAM, "\n"])
        # Home Run
        elif info['event'] == 'Home Run' and info['rbi'] != 4: # ("homers" in ) or ("home run" in info['description']):
            emoji = ''.join([emoji, constants.EMOTE_HOMERUN if favTeamIsBatting else constants.EMOTE_OTHER_TEAM_HOMERUN, "\n"])
        # RBIs
        for rbis in range(info['rbis']):
            emoji = ''.join([emoji, constants.EMOTE_RBI if favTeamIsBatting else constants.EMOTE_OTHER_TEAM_RBI, " "])

        if 'scores' in info['description']:  # Bugfix for if a batter scores on a stolen base or wild pitch, because the atbat still has a run scored even if the batter pops out
            # Earned runs that are not RBIs (run scores on GIDP)
            for earnedRunsNotRBIs in range(info['runsEarned'] - info['rbis']):
                emoji = ''.join([emoji, constants.EMOTE_EARNED_RUN if favTeamIsBatting else constants.EMOTE_OTHER_TEAM_EARNED_RUN, " "])
            # Unearned runs
            unearnedRuns = info['runsScored'] - info['rbis'] - info['runsEarned'] if info['runsScored'] - info['rbis'] - info['runsEarned'] > 0 else 0
            for unearnedRunsNotRBIs in range(unearnedRuns):
                emoji = ''.join([emoji, constants.EMOTE_UNEARNED_RUN if favTeamIsBatting else constants.EMOTE_OTHER_TEAM_UNEARNED_RUN, " "])

        return emoji

    def checkIfFavoriteTeam(self, teamId):
        return self.TEAM_ID == teamId

    def formatEndOfGameAnnouncement(self, team1Info, team2Info):
        favTeamInfo = team1Info if self.checkIfFavoriteTeam(team1Info['id']) else team2Info
        opponentTeamInfo = team2Info if self.checkIfFavoriteTeam(team1Info['id']) else team1Info
        beatOrLostTo = "beat" if (favTeamInfo['game_score'] > opponentTeamInfo['game_score']) else "lost to"
        return "The {} {} the {} by a score of {}-{}".format(
            favTeamInfo['teamName'], beatOrLostTo, opponentTeamInfo['teamName'], favTeamInfo['game_score'], opponentTeamInfo['game_score'])

    def favoriteTeamWon(self, team1Info, team2Info):
        favTeamInfo = team1Info if self.checkIfFavoriteTeam(team1Info['id']) else team2Info
        opponentTeamInfo = team2Info if self.checkIfFavoriteTeam(team1Info['id']) else team1Info
        return favTeamInfo['game_score'] > opponentTeamInfo['game_score']

if __name__ == '__main__':
    baseballUpdaterBot = BaseballUpdaterBotV2()
    baseballUpdaterBot.run()
