from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Kind = Literal["I", "J", "L", "O", "S", "T", "Z"]
Control = Literal["left", "right", "down", "clockwise", "counterclockwise", "drop", "hold", "wait"]
CellRow = Annotated[list[Kind | Literal["garbage"] | None], Field(min_length=10, max_length=10)]
ShapeRow = Annotated[list[Literal[0, 1]], Field(min_length=2, max_length=4)]


class GameInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ActivePiece(GameInput):
    kind: Kind
    shape: list[ShapeRow] = Field(min_length=2, max_length=4)
    x: int = Field(ge=-3, le=9)
    y: int = Field(ge=0, le=19)

    @model_validator(mode="after")
    def square_tetromino(self):
        if any(len(row) != len(self.shape) for row in self.shape):
            raise ValueError("Shape must be square")
        if sum(sum(row) for row in self.shape) != 4:
            raise ValueError("Shape must have four occupied cells")
        return self


class TetrisPlacement(GameInput):
    target: ActivePiece
    uses_hold: bool

    @model_validator(mode="after")
    def target_inside_board(self):
        for y, row in enumerate(self.target.shape):
            for x, cell in enumerate(row):
                if cell and not (0 <= self.target.x + x < 10 and 0 <= self.target.y + y < 20):
                    raise ValueError("Landing must fit inside the board")
        return self


class TetrisLanding(TetrisPlacement):
    piece: Kind
    hold_after: Kind | None
    cleared_lines: int = Field(ge=0, le=4)
    holes: int = Field(ge=0, le=200)
    max_height: int = Field(ge=0, le=20)
    aggregate_height: int = Field(ge=0, le=200)
    bumpiness: int = Field(ge=0, le=180)
    key_presses: int = Field(ge=1, le=64)

    @model_validator(mode="after")
    def target_matches_piece(self):
        if self.target.kind != self.piece:
            raise ValueError("Landing must match the piece")
        return self


class TetrisCandidate(TetrisLanding):
    action: Literal["left", "right", "clockwise", "counterclockwise", "drop", "hold"]
    next_piece: Kind | None
    next_spawn_blocked: bool | None
    follow_ups: list[TetrisLanding] = Field(max_length=2)


class TetrisModelChoice(GameInput):
    kind: Literal["decision", "generation"]
    model_id: str = Field(min_length=1, max_length=64)


class TetrisModelOption(TetrisModelChoice):
    name: str
    model_key: str
    provider: str
    is_default: bool


class TetrisModelsResponse(BaseModel):
    models: list[TetrisModelOption]


class TetrisObservation(GameInput):
    board: list[CellRow] = Field(min_length=20, max_length=20)
    active: ActivePiece
    next: Kind
    hold: Kind | None
    can_hold: bool
    score: int = Field(ge=0, le=2_147_483_647)
    lines: int = Field(ge=0, le=2_147_483_647)
    level: int = Field(ge=1, le=214_748_365)


class TetrisDecisionRequest(TetrisObservation):
    model_choice: TetrisModelChoice | None = None
    opponent: TetrisObservation | None = None
    candidates: list[TetrisCandidate] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def active_fits(self):
        for item in self.candidates:
            if item.uses_hold != (item.action == "hold"):
                raise ValueError("Hold action must match the candidate")
            if item.uses_hold and not self.can_hold:
                raise ValueError("Hold is not available")
            piece = (self.hold or self.next) if item.uses_hold else self.active.kind
            reserve = self.active.kind if item.uses_hold else self.hold
            next_piece = None if item.uses_hold and self.hold is None else self.next
            if (item.piece, item.hold_after, item.next_piece) != (piece, reserve, next_piece):
                raise ValueError("Candidate must use visible pieces")
            if next_piece is None:
                if item.next_spawn_blocked is not None or item.follow_ups:
                    raise ValueError("Unknown next piece cannot be forecast")
            elif item.next_spawn_blocked is None or (item.next_spawn_blocked and item.follow_ups):
                raise ValueError("Forecast must respect next spawn")
            for future in item.follow_ups:
                if future.uses_hold and reserve is None:
                    raise ValueError("Future empty hold would consume a hidden piece")
                future_piece = reserve if future.uses_hold else next_piece
                future_hold = next_piece if future.uses_hold else reserve
                if (future.piece, future.hold_after) != (future_piece, future_hold):
                    raise ValueError("Forecast must use visible pieces")
        for y, row in enumerate(self.active.shape):
            for x, cell in enumerate(row):
                if not cell:
                    continue
                bx, by = self.active.x + x, self.active.y + y
                if not (0 <= bx < 10 and 0 <= by < 20) or self.board[by][bx] is not None:
                    raise ValueError("Active piece must fit the board")
        return self


class TetrisDecisionResponse(BaseModel):
    action: Control
    placement: TetrisPlacement | None
    latency_ms: int = Field(ge=0)
    model: str
    provider: str
    kind: Literal["decision", "generation"]
