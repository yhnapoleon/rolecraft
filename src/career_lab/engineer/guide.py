"""Operator instructions, versioned separately from authorized package data."""


def handoff_guide(language: str) -> bytes:
    if language == "zh":
        text = """# 工程师基线任务包

config.json 是导出时的配置；test 文件保留各次测试自己的历史配置和原始结果。
materials.json 是获准的案例材料；public-probes.json 只含公开问题，不含标准答案。
所选测试是待调查记录，成功复现不代表回答正确或问题已修复。
复现须在可信本机使用原始运行库、当前有效凭据和匹配的已安装场景；这些不随包外发。
请由环境操作者替换下面的路径。凭据为含 api_url、session_id、token 的私有 JSON（权限 0600）。
token 不能写到命令参数中。
"""
    else:
        text = """# Engineering baseline package

config.json is the configuration at export time; each test retains its own historical
configuration and recorded result.
materials.json contains authorized cases; public-probes.json contains public questions
without expected answers.
Selected tests are investigation inputs. Reproducing behavior does not prove correctness
or a repair.
Run on the trusted local host with the original database, current credentials and matching
installed scenario. These are not included in the package.
Ask the environment operator to supply the paths below. Credentials are private JSON with
api_url, session_id and token (mode 0600); keep tokens out of command arguments.
"""
    command = (
        "career-lab-engineer reproduce --pack <package-directory> "
        "--database <original.db> --credentials <private.json> "
        "--scenario <installed-scenario-directory> --output <new-report-directory>"
    )
    return (text + "\n```sh\n" + command + "\n```\n").encode("utf-8")
