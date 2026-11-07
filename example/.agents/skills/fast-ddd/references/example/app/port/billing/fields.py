from typing import Annotated

from pydantic import Field

# HTTP requests and task payloads share it, so neither transport's contract drives the other.
type Reason = Annotated[str, Field(min_length=1, max_length=200)]
