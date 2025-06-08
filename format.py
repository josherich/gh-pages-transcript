import os
from env import *
from openai import AsyncOpenAI
from google import genai
from langchain_text_splitters import RecursiveCharacterTextSplitter
import asyncio

openai_client = AsyncOpenAI()
ollama_client = AsyncOpenAI(
    base_url=os.getenv("OLLAMA_URL"),
    # required but ignored
    api_key='ollama',
)
basement_client = AsyncOpenAI(
    base_url=os.getenv("BASEMENT_URL"),
)
g_client = genai.Client(api_key=os.getenv("G_TOKEN"))

lm_provider = os.getenv("LM_PROVIDER", "google")

# Here are some writing samples to ground your style and tone:
# {samples}
samples = [

]

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

def get_rewrite_template():
    template = """Rewrite the following transcript part for better readability.
- Important!: rewrite MUST be done one paragraph at a time. Do not combine multiple paragraphs into one. Do not skip any paragraphs. Do not add any new information.
- Use markdown syntax when it helps to improve readability.
- Don't overuse bullet points, although some are okay.
- If there are multiple speakers, add proper spearker labels, you can infer speaker's name from the context.
- if it's a conversation, keep the conversation tone.
- If you think a particular picture or screenshot might be interesting at a certain point, go ahead and put a placeholder with some kind of caption that indicates what the picture might be.
- This is part of the transcript, do not add introduction or conclusion if the part is in the middle.
- Use previous finished part if present, to keep consistency and improve transition.

(改写以下转录文字（部分），以提高可读性。
- 重要！：改写必须逐段进行。不要将多个段落合并为一个。不要跳过任何段落。不要添加任何新信息。
- 在有助于提高可读性的情况下使用 markdown 语法。
- 不要过多使用列表，但是一些是可以的。
- 如果有多个发言者，请添加说话人标签。
- 如果这是对话，请保持对话的语气。
- 如果您认为特定的图片或截图在某个地方可能很有趣，请放置一个占位符，并附上一些说明，指出图片可能是什么。
- 这是转录文字的一部分，如果这部分在中间，请不要添加介绍或结论。
- 如果有之前已完成的部分，请使用以保持一致性和改进过渡。):

(Optional) Here's a previous finished part for consistency and transition(这是上一个已完成的结果，请保持一致性和过渡):
{previous}

transcript part(部分转录文字):
{content}
"""
    return template

def get_extract_toc_template():
    template = """generate a table of contents for the following text
- give the first sentence, or at least 10 words (exact words) for each section, put it in index_sentences
- organize contents to sections and subsections
- give each section's title and list level (1 to 5)

{content}
"""
    return template

def get_extract_toc_schema():
    return {
        "type": "object",
        "properties": {
          "index": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "index_sentences": {
                  "type": "string"
                },
                "section_title": {
                  "type": "string"
                },
                "section_level": {
                  "type": "integer"
                }
              },
              "required": [
                "index_sentences",
                "section_title",
                "section_level"
              ]
            }
          }
        }
      }

def get_faq_template():
    template = """Generate a list of questions (5 to 10) and answers for the following text
- give the first sentence, or at least 10 words (exact words) for each answer's source, put it in index_of_source so that the answer's source can be located.
- ask questions about main arguments or points of interest.
- ask questions about unintuitive things in the content.
- ask questions about potential contradictions.
- ask whys and hows questions not directly addressed by the content.

为以下内容生成一系列问题（5到10个）和答案
- 将每个答案的来源的第一句原文放在index_of_source中，以便定位答案的来源。
- 针对主要论点或感兴趣的点提出问题。
- 针对内容中反直觉的内容提出问题。
- 针对潜在的矛盾提出问题。
- 针对原文未回答或含糊的内容提出问题。

{content}
"""
    return template

def get_faq_schema():
    return {
        "type": "object",
        "properties": {
          "qas": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "question": {
                  "type": "string"
                },
                "answer": {
                  "type": "string"
                },
                "index_of_source": {
                  "type": "string"
                }
              },
              "required": [
                "question",
                "answer",
                "index_of_source"
              ]
            }
          }
        }
      }

async def run_with_limit(tasks, concurrency_limit):
    """Run a list of callables with a concurrency limit."""
    semaphore = asyncio.Semaphore(concurrency_limit)

    async def sem_task(func):
        async with semaphore:
            return await func()

    return await asyncio.gather(*[asyncio.create_task(sem_task(t)) for t in tasks])

async def format_transcript(transcription, n=3):
    """split transcript into n parts and format each part"""
    if not transcription:
        return ""

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=5000,
        chunk_overlap=0
    )
    chunks = text_splitter.split_text(transcription)

    tasks = [lambda n=chunk,idx=i: format_transcript_part(n, idx+1) for i, chunk in enumerate(chunks)]
    formatted_parts = await run_with_limit(tasks, concurrency_limit=n)
    return "\n".join(formatted_parts)

async def format_transcript_part(transcription, part_n=1):
    if len(transcription) == 0:
        return ""

    content = get_template().format(content=transcription)
    print(f"------------ Runtime prompt {part_n} -----------")
    print(f"{content[0:100]} ... \n(length: {len(content)})")
    print(f'------------------------------------------------')
    return await answer_prompt(content, part_n)

def answer_prompt_w_schema(content, schema):
    response = g_client.models.generate_content(
        model='gemini-2.5-flash-preview-04-17',
        contents=content,
        config={
            'responseSchema': schema,
            'response_mime_type': 'application/json'
        }
    )
    res = response.text
    return res

def print_res_summary(res, part_n=1):
    print(f"------------ Generated content {part_n} -----------")
    print(f"{res[0:100]} ... \n(length: {len(res)})")

async def answer_prompt(content, part_n=1):
    try:
        if lm_provider == "openai":
            response = await openai_client.chat.completions.create(
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

            print_res_summary(res, part_n)
            return res
        elif lm_provider == "ollama":
            response = await ollama_client.chat.completions.create(
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

            print_res_summary(res, part_n)
            return res
        elif lm_provider == "google":
            response = await g_client.aio.models.generate_content(model='gemini-2.0-flash', contents=content)
            res = response.text
            if len(res.strip()) == 0:
                raise Exception(f"Failed to generate content part {part_n}: empty response, with provider {lm_provider}")

            print_res_summary(res, part_n)
            return res
        elif lm_provider == "basement":
            response = await basement_client.chat.completions.create(
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

            print_res_summary(res, part_n)
            return res
        else:
            raise Exception(f"Unsupported language model provider: {lm_provider}")
    except Exception as e:
        print(f"Failed to generate content part {part_n}: {e}")
        raise Exception(f"Failed to generate content part {part_n}: {e}")

def rewrite_transcript(transcription, n=3):
    lines = transcription.split("\n")
    line_num = len(lines)

    if line_num < 200:
        return rewrite_transcript_part(transcription)

    part_size = line_num // n
    parts = [lines[i:i+part_size] for i in range(0, line_num, part_size)]

    previous_part = ''
    formatted_parts = []
    for i, part in enumerate(parts):
        formatted_parts.append(rewrite_transcript_part("\n".join(part).strip(), i+1, previous_part))
        previous_part = formatted_parts[-1]

    return "\n".join(formatted_parts)

def rewrite_transcript_part(transcription, part_n=1, previous=''):
    if len(transcription) == 0:
        return ""

    content = get_rewrite_template().format(content=transcription, previous=previous)
    print(f"------------ Runtime prompt {part_n} -----------\n{content[0:100]} ... \n(length: {len(content)})")
    print(f'---------------------------------------\n')
    return answer_prompt(content, part_n)

def extract_toc(text):
    runtime_prompt = get_extract_toc_template().format(content=text)
    print(f"------------ Runtime prompt -----------\n{runtime_prompt[0:100]} ... \n(length: {len(runtime_prompt)})")
    print(f'---------------------------------------\n')
    return answer_prompt_w_schema(runtime_prompt, get_extract_toc_schema())

def extract_faq(text):
    runtime_prompt = get_faq_template().format(content=text)
    print(f"------------ Runtime prompt -----------\n{runtime_prompt[0:100]} ... \n(length: {len(runtime_prompt)})")
    print(f'---------------------------------------\n')
    return answer_prompt_w_schema(runtime_prompt, get_faq_schema())

if __name__ == "__main__":
    transcription = 'test'
    with open('tests/cn-1.txt', 'r') as f:
        transcription = f.read()

    res = format_transcript(transcription)
    print('----------------- format transcript cn-1 ---------------\n')
    print('before n of lines: ', transcription.count('\n'))
    print('after n of lines: ', res.count('\n'))
    print(res)

    rewrite = rewrite_transcript(res)
    print('----------------- rewrite transcript cn-1 --------------\n')
    print('before n of lines: ', transcription.count('\n'))
    print('after n of lines: ', rewrite.count('\n'))
    print(rewrite)

    toc = extract_toc(res)
    print('----------------- extract toc cn-1 ---------------\n')
    print(toc)

    with open('tests/en-1.txt', 'r') as f:
        transcription = f.read()

    res = format_transcript(transcription)
    print('----------------- format transcript en-1 ---------------\n')
    print('before n of lines: ', transcription.count('\n'))
    print('after n of lines: ', res.count('\n'))
    print(res)

    rewrite = rewrite_transcript(res)
    print('----------------- rewrite transcript en-1 --------------\n')
    print('before n of lines: ', transcription.count('\n'))
    print('after n of lines: ', rewrite.count('\n'))
    print(rewrite)

    toc = extract_toc(res)
    print('----------------- extract toc en-1 ---------------\n')
    print(toc)

