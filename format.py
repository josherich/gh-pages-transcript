import os
from env import *
from openai import OpenAI
from google import genai

openai_client = OpenAI()
ollama_client = OpenAI(
    base_url=os.getenv("OLLAMA_URL"),
    # required but ignored
    api_key='ollama',
)
basement_client = OpenAI(
    base_url=os.getenv("BASEMENT_URL"),
)
g_client = genai.Client(api_key=os.getenv("G_TOKEN"))

lm_provider = os.getenv("LM_PROVIDER", "google")

def get_template():
    template = """add paragraphs to the text
- keep all the content word by word
- do not add any content or words
- remove timestamps (e.g. start second - duration second)
- remove filter words (e.g. um, uh, like, you know)
- fix typos and punctuations
- only give the final result
(给以下文字分段
- 原封不动保留所有文
- 不添加原文以外的任何文
- 删除时间戳
- 删除填充词（如：嗯，啊，就是）
- 只修正错别字和标点，
- 只输出最终结果):

{content}
"""
    return template

def format_transcript(transcription, n=3):
    """split transcript into n parts and format each part"""
    lines = transcription.split("\n")
    line_num = len(lines)

    if line_num < 200:
        return format_transcript_part(transcription)

    part_size = line_num // n
    parts = [lines[i:i+part_size] for i in range(0, line_num, part_size)]
    formatted_parts = [format_transcript_part("\n".join(part).strip(), i+1) for i, part in enumerate(parts)]
    return "\n".join(formatted_parts)

def format_transcript_part(transcription, part_n=1):
    if len(transcription) == 0:
        return ""

    content = get_template().format(content=transcription)
    print(f"------------ Runtime prompt {part_n} -----------\n{content[0:100]} ... \n(length: {len(content)})")
    print(f'---------------------------------------\n')
    try:
        if lm_provider == "openai":
            response = openai_client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": content,
                    }
                ],
                model="gpt-4o-mini",
                max_completion_tokens=16384, # max tokens for GPT-4o-mini
            )
            res = response.choices[0].message.content
            if len(res.strip()) == 0:
                raise Exception(f"Failed to generate content part {part_n}: empty response, with provider {lm_provider}")

            print(f"------------ Generated content -----------\n{res[0:100]} ... \n(length: {len(res)})")
            return res
        elif lm_provider == "ollama":
            response = ollama_client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": content,
                    }
                ],
                model="qwen2.5",
            )
            res = response.choices[0].message.content
            if len(res.strip()) == 0:
                raise Exception(f"Failed to generate content part {part_n}: empty response, with provider {lm_provider}")

            print(f"------------ Generated content -----------\n{res[0:100]} ... \n(length: {len(res)})")
            return res
        elif lm_provider == "google":
            response = g_client.models.generate_content(model='gemini-2.0-flash', contents=content)
            res = response.text
            if len(res.strip()) == 0:
                raise Exception(f"Failed to generate content part {part_n}: empty response, with provider {lm_provider}")

            print(f"------------ Generated content -----------\n{res[0:100]} ... \n(length: {len(res)})")
            return res
        elif lm_provider == "basement":
            response = basement_client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": content,
                    }
                ],
                model="deepseek-ai/deepseek-llm-7b-chat",
                max_completion_tokens=2096, # max tokens
            )
            res = response.choices[0].message.content
            if len(res.strip()) == 0:
                raise Exception(f"Failed to generate content part {part_n}: empty response, with provider {lm_provider}")

            print(f"------------ Generated content -----------\n{res[0:100]} ... \n(length: {len(res)})")
            return res
        else:
            raise Exception(f"Unsupported language model provider: {lm_provider}")
    except Exception as e:
        print(f"Failed to generate content part {part_n}: {e}")
        raise Exception(f"Failed to generate content part {part_n}: {e}")

if __name__ == "__main__":
    transcription = 'test'
    with open('tests/cn-1.txt', 'r') as f:
        transcription = f.read()

    res = format_transcript(transcription)
    print('-----------------\n')
    print('before n of lines: ', transcription.count('\n'))
    print('after n of lines: ', res.count('\n'))
    print(res)

    with open('tests/en-1.txt', 'r') as f:
        transcription = f.read()

    res = format_transcript(transcription)
    print('-----------------\n')
    print('before n of lines: ', transcription.count('\n'))
    print('after n of lines: ', res.count('\n'))
    print(res)
