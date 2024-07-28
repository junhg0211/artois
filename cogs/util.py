from discord import Interaction
from discord.app_commands import command, describe
from discord.ext.commands import Cog, Bot

diacritics = {
  "=.": "̇", "='": "́", "=o": "̊", "=\"": "̈", "=-": "̄", "=(": "̑", "=''": "̋",
  "=^": "̂", "=u": "̆", "=v": "̌", "=x": "̽", "=`": "̀", "=``": "̏", "=_^": "̭",
  "=_[": "̪", "=^": "̂", "=~": "̃", "=_.": "̣", "=_\"": "̤", "=)": "͗"
}


class DictionaryCog(Cog):
    @command(name="다이어크리틱", description="문자열에 다이어크리틱을 붙입니다.")
    @describe(string="변경할 문자열")
    async def search(self, ctx: Interaction, string: str):
        for key, value in sorted(diacritics.items(), key=lambda x: len(x[0]), reverse=True):
            string = string.replace(key, value)
        await ctx.response.send_message(f'```\n{string}```')


async def setup(bot: Bot):
    await bot.add_cog(DictionaryCog(bot))
