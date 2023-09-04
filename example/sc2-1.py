from sc2.bot_ai import BotAI  # parent class we inherit from
from sc2.data import Difficulty, Race  # difficulty for bots, race for the 1 of 3 races
from sc2.main import run_game  # function that facilitates actually running the agents in games
from sc2.player import Bot, Computer  #wrapper for whether or not the agent is one of your bots, or a "computer" player
from sc2 import maps  # maps method for loading maps to play in.

class IncrediBot(BotAI): # inhereits from BotAI (part of BurnySC2)
    async def on_step(self, iteration: int): # on_step is a method that is called every step of the game.
        print(f"This is my bot in iteration {iteration}") # prints out the iteration number (ie: the step).

run_game(  # run_game is a function that runs the game.
    maps.get("2000AtmospheresAIE"),  # the map we are playing on
    [Bot(Race.Protoss, IncrediBot()),  # runs our coded bot, protoss race, and we pass our bot object
        Computer(Race.Zerg, Difficulty.Hard)],  # runs a pre-made computer agent, zerg race, with a hard difficulty.
    realtime=False,  # When set to True, the agent is limited in how long each step can take to process.
)
