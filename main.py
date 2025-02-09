from env import *

from fasthtml.common import *
from fastcore.utils import *
import asyncio

from q import main

app,rt = fast_app()

@rt('/')
def get(): return Div(P('Hello World!'), hx_get="/change")

serve(port=5002)

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Shutting down job queue...")
