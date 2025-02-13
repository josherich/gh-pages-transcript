from env import *
from openai import OpenAI
from google import genai

openai_client = OpenAI()
g_client = genai.Client(api_key=os.getenv("G_TOKEN"))

lm_provider = os.getenv("LM_PROVIDER", "google")

def get_template():
    template = """add paragraphs to the text while keeping all the content word by word, remove timestamps:

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
    print(f"------------ Runtime prompt -----------\n{content[0:100]} ... \n(length: {len(content)})")
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
        elif lm_provider == "google":
            response = g_client.models.generate_content(model='gemini-2.0-flash', contents=content)
            res = response.text
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
    transcription = """0.919 - 7.241: our next speaker is Dr Norman JY Norman
5.16 - 4.76: jopy is a Google fellow he has been the
8.16 - 4.16: technical lead for Google's tensor
9.92 - 3.36: processing units since their Inception
12.32 - 3.76: in
13.28 - 5.079: 2013 Norm has a long and distinguished
16.08 - 4.84: record of innovation in high performance
18.359 - 5.401: processors memory hierarchies and
20.92 - 6.24: storage systems and he was the principal
23.76 - 8.2: architect and lead designer of several
27.16 - 4.8: microprocessors please welcome Dr Norman
32.5 - 5.35: [Applause]
41.2 - 5.44: tropy hi
43.879 - 6.68: thanks
46.64 - 3.919: thanks clicker
50.92 - 3.0: yes
56.84 - 7.2: okay so the title of my presentation is
60.039 - 6.801: is immense scale machine learning and uh
64.04 - 6.079: you may wonder why I chose the term
66.84 - 5.88: immense so there's a lot of extreme
70.119 - 6.841: stuff going around but I I think of a
72.72 - 7.16: immense as being relatively good where
76.96 - 6.72: extreme reminds me of for example
79.88 - 6.52: jumping off a cliff in a wing suit so uh
83.68 - 2.72: I went with IM
87.159 - 5.801: M okay we're covering the big the small
90.04 - 5.759: in the not right at all because I think
92.96 - 7.519: those are the three of the largest
95.799 - 7.721: issues um that we face with very large
100.479 - 3.041: uh ml
103.719 - 7.201: models so first of all I'm going to dive
107.24 - 6.4: down the key principles uh
110.92 - 4.6: foundationals in several different areas
113.64 - 4.64: to explain how we came to the design
115.52 - 5.8: decisions that that we
118.28 - 6.759: did so
121.32 - 5.919: uh this chart here
125.039 - 4.681: shows oops
127.239 - 5.64: sorry the energy
129.72 - 5.879: breakdown of uh typical instruction
132.879 - 6.44: execution in a
135.599 - 7.081: CPU and you can see that if we have a
139.319 - 8.601: 8bit ad it's 0.03
142.68 - 7.44: PS where the whole instruction is 70 PS
147.92 - 5.12: so that means that we're getting less
150.12 - 6.479: than 1% efficiency if we're executing
153.04 - 7.0: this 8bit ad on a
156.599 - 6.0: CPU"""

    res = format_transcript(transcription)
    print('-----------------\n')
    print('before n of lines: ', transcription.count('\n'))
    print('after n of lines: ', res.count('\n'))
    print(res)
