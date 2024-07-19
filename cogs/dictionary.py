import re
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict, field
from json import load, dump

from discord import Interaction, Embed, Reaction, Member, MessageType
from discord.app_commands import command, Group, Choice, describe
from discord.ext.commands import Cog, Bot
from gspread.exceptions import SpreadsheetNotFound

from consts import get_const
from database import Database
from util import generate_dictionary_url, similarity


@dataclass
class Dictionary:
    name: str
    spreadsheet_id: str
    sheet_index: int
    author: int
    database: Database
    word_column: int = 0
    exclude_columns: list[int] = field(default_factory=list)
    hidden_columns: list[int] = field(default_factory=list)
    color: int = get_const("color.main")

    @staticmethod
    def dict_factory(x):
        exclude_fields = ["database"]
        return {k: v for (k, v) in x if ((v is not None) and (k not in exclude_fields))}

    def get_embed(self, bot: Bot) -> Embed:
        # create embed
        embed = Embed(
            colour=self.color,
            title=f"`{self.name}` 사전",
            url=generate_dictionary_url(self.spreadsheet_id),
        )

        # add fields
        author = bot.get_user(self.author)
        embed.add_field(name="스프레드시트 ID", value=f"{self.spreadsheet_id}", inline=False)
        embed.add_field(name="이름", value=f"{self.name}")
        embed.add_field(name="시트 인덱스", value=f"{self.sheet_index + 1}")
        if author is not None:
            embed.add_field(name="제작자", value=f"{author.mention}")
        embed.add_field(name="단어 열", value=f"{self.word_column + 1}")
        embed.add_field(name="색상", value=f"#{self.color:06X}")
        embed.add_field(name="제외 열", value=f"{list(map(lambda x: x + 1, self.exclude_columns))}")
        embed.add_field(name="숨김 열", value=f"{list(map(lambda x: x + 1, self.hidden_columns))}")
        embed.add_field(name="단어 수", value=f"{len(self.database.sheet_values)-1}개")

        return embed


def load_dictionary(dictionary_json) -> Dictionary:
    """ `dictionary_json`정보로부터 `Dictionary` 객체를 만들어냅니다. """
    spreadsheet_id = dictionary_json["spreadsheet_id"]
    sheet_index = dictionary_json["sheet_index"]
    database = Database(spreadsheet_id, sheet_index)
    return Dictionary(database=database, **dictionary_json)


class DictionaryCog(Cog):
    def __init__(self, bot):
        self.bot: Bot = bot

        # load dictionaries from file
        with open("res/dictionaries.json", "r", encoding="utf-8") as file:
            self.dictionaries: list[Dictionary] = list(map(load_dictionary, load(file)))

    def dump_dictionaries(self):
        """ `self.dictionaries`를 파일로 저장합니다. """
        with open("res/dictionaries.json", "w", encoding="utf-8") as file:
            data = list(
                map(lambda x: asdict(x, dict_factory=x.dict_factory), self.dictionaries)
            )
            dump(data, file, ensure_ascii=False)
    
    @Cog.listener()
    async def on_reaction_add(self, reaction: Reaction, user: Member):
        """ 커맨드 사용자가 `🗑` 이모지를 남기면️ 메시지를 삭제합니다. """
        if reaction.emoji != '🗑️':
            return
        if reaction.message.author.id != self.bot.user.id:
            return
        if reaction.message.type != MessageType.chat_input_command:
            return
        if reaction.message.interaction_metadata.user != user.id:
            return
        await reaction.message.delete()

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
        # get dictionary object
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

        # check if last greater than 7 days from last reload
        reloading = database.last_reload + timedelta(days=7) < datetime.now()
        if reloading:
            await ctx.response.defer(ephemeral=ephemeral)
            database.reload()

        # search rows by query
        rows = await database.search_rows(
            query, dictionary.word_column, dictionary.exclude_columns, dictionary.hidden_columns
        )

        # create result embed
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

        # send result message
        if reloading:
            await ctx.edit_original_response(embed=embed)
        else:
            await ctx.response.send_message(embed=embed, ephemeral=ephemeral)

    dictionary_group = Group(name="사전", description="사전을 관리합니다.")

    @dictionary_group.command(name="정보", description="사전의 정보를 확인합니다.")
    @describe(name="사전 이름")
    async def dictionary_info(self, ctx: Interaction, name: str):
        # get dictionary object
        try:
            dictionary = next(filter(lambda x: x.name == name, self.dictionaries))
        except StopIteration:
            await ctx.response.send_message(
                f"이름이 `{name}`인 사전을 찾을 수 없습니다.", ephemeral=True
            )
            return

        # send result message
        await ctx.response.send_message(
            embed=dictionary.get_embed(self.bot), ephemeral=True
        )

    @dictionary_group.command(name="추가", description="사전을 추가합니다.")
    @describe(
        name="사전 이름",
        spreadsheet_id="사전의 스프레드시트 아이디",
        sheet_index="사전의 시트 번호",
    )
    async def dictionary_add(
        self, ctx: Interaction, name: str, spreadsheet_id: str, sheet_index: int
    ):
        sheet_index -= 1

        await ctx.response.defer(ephemeral=True)

        # check duplicate dictionary name
        for dictionary in self.dictionaries:
            if name == dictionary.name:
                await ctx.edit_original_response(
                    content=f"언어가 `{name}`인 언어가 이미 존재합니다.",
                )
                return

        # make database object
        try:
            database = Database(spreadsheet_id, sheet_index)
        except PermissionError:
            await ctx.edit_original_response(
                content='사전을 불러오지 못했습니다. 사전이 공개되어있는지 확인해주세요.'
            )
            return
        except SpreadsheetNotFound:
            await ctx.edit_original_response(
                content='사전을 불러오지 못했습니다. 사전 링크가 올바른지 확인해주세요.'
            )
            return

        # append dictionary to dictionary index
        dictionary = Dictionary(
            name, spreadsheet_id, sheet_index, ctx.user.id, database
        )
        self.dictionaries.append(dictionary)
        self.dump_dictionaries()

        # send result message
        await ctx.edit_original_response(
            content=f"언어 `{name}`의 사전이 추가되었습니다. "
                    f"`/사전 설정` 명령어를 통해 사전의 설정을 바꾸거나 수정할 수 있습니다."
        )

    @dictionary_group.command(name="목록", description="사전의 목록을 확인합니다.")
    async def dictionary_list(self, ctx: Interaction):
        names = list()
        for dictionary in self.dictionaries:
            names.append(f"`{dictionary.name}`")
        names.sort()
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
        # get dictionary object
        try:
            dictionary = next(filter(lambda x: x.name == name, self.dictionaries))
        except StopIteration:
            await ctx.response.send_message(
                f"이름이 `{name}`인 사전을 찾을 수 없습니다.", ephemeral=True
            )
            return

        # check dictionary author
        if dictionary.author != ctx.user.id:
            await ctx.response.send_message(
                f"사전은 사전 작성자만 삭제할 수 있습니다.", ephemeral=True
            )
            return

        # remove dictionary
        self.dictionaries.remove(dictionary)
        self.dump_dictionaries()

        # send result message
        await ctx.response.send_message(
            f"`{name}` 사전을 제거했습니다.", ephemeral=True
        )

    @dictionary_group.command(name="설정", description="사전의 설정을 수정합니다.")
    @describe(name="설정할 사전 이름", property="설정할 항목 이름", value="설정 값")
    async def dictionary_setting(
        self, ctx: Interaction, name: str, property: str, value: str
    ):
        # get dictionary object
        try:
            dictionary = next(filter(lambda x: x.name == name, self.dictionaries))
        except StopIteration:
            await ctx.response.send_message(
                f"이름이 `{name}`인 사전을 찾을 수 없습니다.", ephemeral=True
            )
            return

        # check dictionary author
        if dictionary.author != ctx.user.id:
            await ctx.response.send_message(
                f"사전은 사전 작성자만 설정할 수 있습니다.", ephemeral=True
            )
            return

        if property == "color":
            # fetch color
            value = value.lower()
            color_re = re.compile(r"#[0-9a-f]{6}")
            if color_re.fullmatch(value) is None:
                await ctx.response.send_message(
                    "색은 `#000000` 형식으로 입력해야 합니다.", ephemeral=True
                )
                return

            # change dictionary color
            dictionary.color = int(value[1:], 16)
            self.dump_dictionaries()

            # send result message
            await ctx.response.send_message(
                f"사전의 색상을 `{value}`로 설정했습니다.", ephemeral=True
            )
            return

        if property == "exclude_column":
            # fetch column indexes
            if value == '0':
                numbers = list()
            else:
                try:
                    numbers = list(map(lambda x: int(x) - 1, sorted(set(value.split(",")))))
                except ValueError:
                    await ctx.response.send_message(
                        "제외 열은 `,`로 구분된 정수들 또는 `0`(없음)으로만 입력해야 합니다.", ephemeral=True
                    )
                    return

            # set exclude column indexes
            dictionary.exclude_columns = numbers
            self.dump_dictionaries()

            # send result message
            await ctx.response.send_message(
                f"제외 열을 `{list(map(lambda x: x + 1, dictionary.exclude_columns))}`(으)로 설정했습니다.",
                ephemeral=True,
            )
            return

        if property == "word_column":
            # fetch word column
            try:
                word_column = int(value)
            except ValueError:
                await ctx.response.send_message(
                    "단어 열은 정수를 입력해야 합니다.", ephemeral=True
                )
                return

            # word column validation
            if 1 > word_column:
                await ctx.response.send_message(
                    "단어 열은 1 이상의 정수를 입력해야 합니다.", ephemeral=True
                )
                return
            if word_column > len(dictionary.database.sheet_values[0]):
                await ctx.response.send_message(
                    "단어 열 인덱스가 열 개수를 초과합니다.", ephemeral=True
                )
                return
            word_column -= 1

            # set word column
            dictionary.word_column = word_column
            self.dump_dictionaries()

            # send result message
            await ctx.response.send_message(
                f"단어 열을 `{dictionary.word_column + 1}`(으)로 설정했습니다.",
                ephemeral=True,
            )
            return
        
        if property == "sheet_index":
            # fetch sheet index
            try:
                new_sheet_index = int(value)
            except ValueError:
                await ctx.response.send_message(
                    "시트 인덱스는 정수를 입력해야 합니다.", ephemeral=True
                )
                return

            # sheet index validation
            if 1 > new_sheet_index:
                await ctx.response.send_message(
                    "시트 인덱스는 1 이상의 정수를 입력해야 합니다.", ephemeral=True
                )
                return
            new_sheet_index -= 1

            # set sheet index
            dictionary.sheet_index = new_sheet_index
            self.dump_dictionaries()

            # send result message
            await ctx.response.send_message(
                f"시트 인덱스를 `{dictionary.sheet_index + 1}`(으)로 설정했습니다.",
                ephemeral=True,
            )
            return

        if property == "name":
            # dictionary name duplication check
            for d in self.dictionaries:
                if d.name == value:
                    await ctx.response.send_message(
                        f"이름이 `{value}`인 사전이 이미 존재합니다.", ephemeral=True,
                    )
                    return
            
            # set dictionary name
            dictionary.name = value
            self.dump_dictionaries()

            # send result message
            await ctx.response.send_message(
                f'사전 이름을 `{value}`(으)로 설정했습니다.', ephemeral=True
            )
            return

        if property == "hidden_column":
            # fetch column indexes
            if value == '0':
                numbers = list()
            else:
                try:
                    numbers = list(map(lambda x: int(x) - 1, sorted(set(value.split(",")))))
                except ValueError:
                    await ctx.response.send_message(
                        "숨김 열은 `,`로 구분된 정수들 또는 `0`(없음)으로만 입력해야 합니다.", ephemeral=True
                    )
                    return
            
            # set hidden column
            dictionary.hidden_columns = numbers
            self.dump_dictionaries()

            # send result message
            await ctx.response.send_message(
                f'숨김 열을 `{list(map(lambda x: x+1, dictionary.hidden_columns))}`(으)로 설정했습니다.',
                ephemeral=True
            )
            return

        await ctx.response.send_message("설정 정보를 찾을 수 없습니다.", ephemeral=True)

    @dictionary_setting.autocomplete("property")
    async def dictionary_setting_property_autocomplete(
        self, _ctx: Interaction, current: str
    ) -> list[Choice[str]]:
        options = [
            ("색상", "color"),
            ("제외 열", "exclude_column"),
            ("단어 열", "word_column"),
            ("시트 인덱스", "sheet_index"),
            ("이름", "name"),
            ("숨김 열", "hidden_column"),
        ]

        similarities = sorted(
            filter(lambda x: current in x[0], options),
            key=lambda x: similarity(x[0], current),
            reverse=True)

        return list(map(lambda x: Choice(name=x[0], value=x[1]), similarities))

    @dictionary_group.command(name='새로고침', description='사전을 다시 불러옵니다.')
    async def dictionary_reload(self, ctx: Interaction, name: str):
        # get dictionary object
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

        # reload dictionary
        database.reload()

        # send result message
        await ctx.edit_original_response(content=f'`{name}` 사전이 새로고침되었습니다.')

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
        names.sort()
        return list(map(lambda x: Choice(name=x, value=x), names))


async def setup(bot: Bot):
    await bot.add_cog(DictionaryCog(bot))
