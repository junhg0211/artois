import re
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict, field
from json import load, dump

from discord import Interaction, Embed
from discord.app_commands import command, Group, Choice, describe
from discord.ext.commands import Cog, Bot

from consts import get_const
from database import Database
from util import generate_dictionary_url


@dataclass
class Dictionary:
    name: str
    spreadsheet_id: str
    sheet_index: int
    author: int
    database: Database
    word_column: int = 0
    exclude_columns: list[int] = field(default_factory=list)
    color: int = get_const("color.main")

    @staticmethod
    def dict_factory(x):
        exclude_fields = ["database"]
        return {k: v for (k, v) in x if ((v is not None) and (k not in exclude_fields))}

    def get_embed(self, bot: Bot) -> Embed:
        embed = Embed(
            colour=self.color,
            title=f"`{self.name}` 사전",
            url=generate_dictionary_url(self.spreadsheet_id),
        )

        author = bot.get_user(self.author)
        embed.add_field(name="스프레드시트 ID", value=f"{self.spreadsheet_id}", inline=False)
        embed.add_field(name="이름", value=f"{self.name}")
        embed.add_field(name="시트 인덱스", value=f"{self.sheet_index}")
        if author is not None:
            embed.add_field(name="제작자", value=f"{author.mention}")
        embed.add_field(name="단어 열", value=f"{self.word_column}")
        embed.add_field(name="색상", value=f"#{self.color:06X}")
        embed.add_field(name="제외 열", value=f"{self.exclude_columns}")
        embed.add_field(name="단어 수", value=f"{len(self.database.sheet_values)-1}개")

        return embed


def load_dictionary(dictionary) -> Dictionary:
    spreadsheet_id = dictionary["spreadsheet_id"]
    sheet_index = dictionary["sheet_index"]
    database = Database(spreadsheet_id, sheet_index)
    return Dictionary(database=database, **dictionary)


class DictionaryCog(Cog):
    def __init__(self, bot):
        self.bot = bot

        with open("res/dictionaries.json", "r", encoding="utf-8") as file:
            self.dictionaries: list[Dictionary] = list(map(load_dictionary, load(file)))

    def dump_dictionaries(self):
        with open("res/dictionaries.json", "w", encoding="utf-8") as file:
            data = list(
                map(lambda x: asdict(x, dict_factory=x.dict_factory), self.dictionaries)
            )
            dump(data, file, ensure_ascii=False)

    @command(name="검색", description="단어를 검색합니다.")
    @describe(
        conlang_name="검색할 사전의 이름",
        query="검색어",
        count="검색 결과 개수",
        ephemeral="결과 비공개 여부",
    )
    async def search(
        self,
        ctx: Interaction,
        conlang_name: str,
        query: str,
        count: int = 5,
        ephemeral: bool = True,
    ):
        try:
            dictionary = next(
                filter(lambda x: x.name == conlang_name, self.dictionaries)
            )
            database = dictionary.database
        except StopIteration:
            await ctx.response.send_message(
                f"이름이 `{conlang_name}`인 사전을 찾을 수 없습니다.", ephemeral=True
            )
            return

        reloading = database.last_reload + timedelta(days=7) < datetime.now()
        if reloading:
            await ctx.response.defer(ephemeral=ephemeral)
            database.reload()

        rows = await database.search_rows(
            query, dictionary.word_column, dictionary.exclude_columns
        )

        embed = Embed(
            colour=dictionary.color,
            title=f"`{dictionary.name}` 사전의 검색 결과",
            url=generate_dictionary_url(dictionary.spreadsheet_id),
            description=f"`{query}` 검색 결과",
        )
        for word, values in rows[: max(0, min(count, 25))]:
            result = list()
            for key, value in values.items():
                result.append(f"- {key}: {value}")

            embed.add_field(name=word, value=f"\n".join(result))

        if reloading:
            await ctx.edit_original_response(embed=embed)
        else:
            await ctx.response.send_message(embed=embed, ephemeral=ephemeral)

    dictionary_group = Group(name="사전", description="사전을 관리합니다.")

    @dictionary_group.command(name="정보", description="사전의 정보를 확인합니다.")
    @describe(name="사전 이름")
    async def dictionary_info(self, ctx: Interaction, name: str):
        try:
            dictionary = next(filter(lambda x: x.name == name, self.dictionaries))
        except StopIteration:
            await ctx.response.send_message(
                f"이름이 `{name}`인 사전을 찾을 수 없습니다.", ephemeral=True
            )
            return

        await ctx.response.send_message(
            embed=dictionary.get_embed(self.bot), ephemeral=True
        )

    @dictionary_group.command(name="추가", description="사전을 추가합니다.")
    @describe(
        name="사전 이름",
        spreadsheet_id="사전의 스프레드시트 아이디",
        sheet_index="사전의 시트 번호 (0부터 시작)",
    )
    async def dictionary_add(
        self, ctx: Interaction, name: str, spreadsheet_id: str, sheet_index: int
    ):
        await ctx.response.defer(ephemeral=True)

        for dictionary in self.dictionaries:
            if name == dictionary.name:
                await ctx.edit_original_response(
                    content=f"언어가 `{name}`인 언어가 이미 존재합니다.",
                )
                return

        database = Database(spreadsheet_id, sheet_index)
        dictionary = Dictionary(
            name, spreadsheet_id, sheet_index, ctx.user.id, database
        )
        self.dictionaries.append(dictionary)
        self.dump_dictionaries()

        await ctx.edit_original_response(
            content=f"언어 `{name}`의 사전이 추가되었습니다. "
                    f"`/사전 설정` 명령어를 통해 사전의 설정을 바꾸거나 수정할 수 있습니다."
        )

    @dictionary_group.command(name="목록", description="사전의 목록을 확인합니다.")
    async def dictionary_list(self, ctx: Interaction):
        names = list()
        for dictionary in self.dictionaries:
            names.append(f"`{dictionary.name}`")
        names = ", ".join(names)

        if self.dictionaries:
            await ctx.response.send_message(
                f"아르투아가 제공하는 사전 목록입니다.\n> {names}", ephemeral=True
            )
        else:
            await ctx.response.send_message(
                "현재 아르투아는 사전을 제공하지 않습니다.", ephemeral=True
            )

    @dictionary_group.command(name="삭제", description="사전을 삭제합니다.")
    @describe(name="삭제할 사전 이름")
    async def dictionary_delete(self, ctx: Interaction, name: str):
        try:
            dictionary = next(filter(lambda x: x.name == name, self.dictionaries))
        except StopIteration:
            await ctx.response.send_message(
                f"이름이 `{name}`인 사전을 찾을 수 없습니다.", ephemeral=True
            )
            return

        if dictionary.author != ctx.user.id:
            await ctx.response.send_message(
                f"사전은 사전 작성자만 삭제할 수 있습니다.", ephemeral=True
            )
            return

        self.dictionaries.remove(dictionary)
        self.dump_dictionaries()
        await ctx.response.send_message(
            f"`{name}` 사전을 제거했습니다.", ephemeral=True
        )

    @dictionary_group.command(name="설정", description="사전의 설정을 수정합니다.")
    @describe(name="설정할 사전 이름", property="설정할 항목 이름", value="설정 값")
    async def dictionary_setting(
        self, ctx: Interaction, name: str, property: str, value: str
    ):
        try:
            dictionary = next(filter(lambda x: x.name == name, self.dictionaries))
        except StopIteration:
            await ctx.response.send_message(
                f"이름이 `{name}`인 사전을 찾을 수 없습니다.", ephemeral=True
            )
            return

        if dictionary.author != ctx.user.id:
            await ctx.response.send_message(
                f"사전은 사전 작성자만 설정할 수 있습니다.", ephemeral=True
            )
            return

        if property == "color":
            value = value.lower()
            color_re = re.compile(r"#[0-9a-f]{6}")
            if color_re.fullmatch(value) is None:
                await ctx.response.send_message(
                    "색은 `#000000` 형식으로 입력해야 합니다.", ephemeral=True
                )
                return

            dictionary.color = int(value[1:], 16)
            await ctx.response.send_message(
                f"사전의 색상을 `{value}`로 설정했습니다.", ephemeral=True
            )
            self.dump_dictionaries()
            return

        if property == "exclude_column":
            try:
                numbers = map(int, value.split(","))
            except ValueError:
                await ctx.response.send_message(
                    "제외 열은 `,`로 구분된 숫자들로만 입력해야 합니다.", ephemeral=True
                )
                return

            dictionary.exclude_columns = list(numbers)
            await ctx.response.send_message(
                f"제외 열을 `{dictionary.exclude_columns}`(으)로 설정했습니다.",
                ephemeral=True,
            )
            self.dump_dictionaries()
            return

        if property == "word_column":
            try:
                word_column = int(value)
            except ValueError:
                await ctx.response.send_message(
                    "단어 열은 정수를 입력해야 합니다.", ephemeral=True
                )
                return

            if 0 > word_column:
                await ctx.response.send_message(
                    "단어 열은 0 이상의 정수를 입력해야 합니다.", ephemeral=True
                )
                return

            dictionary.word_column = word_column
            await ctx.response.send_message(
                f"단어 열을 `{dictionary.word_column}`(으)로 설정했습니다.",
                ephemeral=True,
            )
            self.dump_dictionaries()
            return

        await ctx.response.send_message("설정 정보를 찾을 수 없습니다.", ephemeral=True)

    @dictionary_group.command(name='새로고침', description='사전을 다시 불러옵니다.')
    async def dictionary_reload(self, ctx: Interaction, name: str):
        try:
            dictionary = next(
                filter(lambda x: x.name == name, self.dictionaries)
            )
            database = dictionary.database
        except StopIteration:
            await ctx.response.send_message(
                f"이름이 `{name}`인 사전을 찾을 수 없습니다.", ephemeral=True
            )
            return

        await ctx.response.defer(ephemeral=True)
        database.reload()
        await ctx.edit_original_response(content=f'`{name}` 사전이 새로고침되었습니다.')

    @dictionary_setting.autocomplete("property")
    async def dictionary_setting_property_autocomplete(
        self, _ctx: Interaction, _current: str
    ) -> list[Choice[str]]:
        return [
            Choice(name="색상", value="color"),
            Choice(name="제외 열", value="exclude_column"),
            Choice(name="단어 열", value="word_column"),
        ]

    @search.autocomplete("conlang_name")
    @dictionary_info.autocomplete("name")
    @dictionary_delete.autocomplete("name")
    @dictionary_setting.autocomplete("name")
    @dictionary_reload.autocomplete("name")
    async def name_autocomplete(
        self, _: Interaction, current: str
    ) -> list[Choice[str]]:
        names = list()
        for dictionary in self.dictionaries:
            if current in dictionary.name:
                names.append(dictionary.name)
        return list(map(lambda x: Choice(name=x, value=x), names))


async def setup(bot: Bot):
    await bot.add_cog(DictionaryCog(bot))
