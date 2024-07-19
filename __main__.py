import re
from asyncio import run
from argparse import ArgumentParser
from os import listdir

from discord import Intents
from discord.ext.commands import Bot, when_mentioned

from consts import get_secret

bot = Bot(when_mentioned, intents=Intents.all())


@bot.event
async def on_ready():
    await bot.tree.sync()


async def load_cogs(cog_re=r".*"):
    filter_pattern = re.compile(cog_re)
    for file in listdir("cogs"):
        # cog name validation
        if not file.endswith(".py") or file.startswith("_"):
            continue
        if filter_pattern.search(file[:-3]) is None:
            continue

        # load cog
        cog_name = file[:-3]
        print(f"Loading cog `{cog_name}` ...", end="\r")
        await bot.load_extension(f"cogs.{cog_name}")
        print(f"Cog loaded: {cog_name}      ")


def parse_args():
    from consts import override_const

    parser = ArgumentParser()

    parser._actions[0].help = "도움말 메시지를 보여주고 종료합니다"
    parser.add_argument(
        "-t",
        "--test",
        action="store_true",
        help="아르투아 봇을 `test_bot_token`으로 실행합니다. "
        "설정되지 않은 경우, `bot_token`으로 실행합니다",
    )
    parser.add_argument(
        "-c",
        "--cog",
        action="store",
        default=r".*",
        help="이 정규표현식을 만족하는 이름을 가진 코그만 실행합니다",
    )
    parser.add_argument(
        "-o",
        "--override",
        action="append",
        help="const를 override합니다. `key=value`의 형태로 입력합니다.",
    )

    args = parser.parse_args()

    if args.test:
        print("Run in test mode ...")

    if args.override:
        for override in args.override:
            key, value = override.split("=")
            override_const(key, eval(value))
            print(f"Constant overlode: {key} = {value}")

    return args


if __name__ == "__main__":
    args = parse_args()
    run(load_cogs(args.cog))
    bot_token = get_secret("test_bot_token" if args.test else "bot_token")
    bot.run(bot_token)