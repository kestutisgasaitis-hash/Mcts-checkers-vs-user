import time

FULL_MASK = (1 << 32) - 1

WHITE = 0
BLACK = 1

STEP_TABLE = {
    WHITE: [[] for _ in range(32)],
    BLACK: [[] for _ in range(32)]
}

JUMP_TABLE = {
    WHITE: [[] for _ in range(32)],
    BLACK: [[] for _ in range(32)]
}

BIT = [1 << i for i in range(32)]

WHITE_DIRS = [(1, -1), (1, 1)]
BLACK_DIRS = [(-1, -1), (-1, 1)]
KING_DIRS  = WHITE_DIRS + BLACK_DIRS

WHITE_LAST_ROW = 0
for sq in range(28, 32):
    WHITE_LAST_ROW |= BIT[sq]

BLACK_LAST_ROW = 0
for sq in range(4):
    BLACK_LAST_ROW |= BIT[sq]


#print(f"WHITE_LAST_ROW = {bin(WHITE_LAST_ROW)}")
#print(f"BLACK_LAST_ROW = {bin(BLACK_LAST_ROW)}")

def init_move_tables():
    for sq in range(32):
        r, c = sq32_to_8x8(sq)

        # ---- WHITE ----
        for dr, dc in [(1, -1), (1, 1)]:
            nr, nc = r + dr, c + dc
            nsq = sq8x8_to_32(nr, nc)
            if nsq is not None:
                STEP_TABLE[WHITE][sq].append(nsq)

            # jump
            mr, mc = r + dr, c + dc
            tr, tc = r + 2*dr, c + 2*dc
            mid = sq8x8_to_32(mr, mc)
            land = sq8x8_to_32(tr, tc)

            if mid is not None and land is not None:
                JUMP_TABLE[WHITE][sq].append((mid, land))

        # ---- BLACK ----
        for dr, dc in [(-1, -1), (-1, 1)]:
            nr, nc = r + dr, c + dc
            nsq = sq8x8_to_32(nr, nc)
            if nsq is not None:
                STEP_TABLE[BLACK][sq].append(nsq)

            mr, mc = r + dr, c + dc
            tr, tc = r + 2*dr, c + 2*dc
            mid = sq8x8_to_32(mr, mc)
            land = sq8x8_to_32(tr, tc)

            if mid is not None and land is not None:
                JUMP_TABLE[BLACK][sq].append((mid, land))

class Board:
    __slots__ = ( 'WP','BP','K')
    def __init__(self, WP=0, BP=0, K=0):
        self.WP = WP
        self.BP = BP
        self.K  = K

    @property
    def empty(self):
        return ~(self.WP | self.BP) & FULL_MASK

    def copy(self):
        return Board(self.WP, self.BP, self.K)

def start_position():
    WP = 0
    BP = 0

    # white 0-11
    for sq in range(12):
        WP |= (1 << sq)

    # black 20-31
    for sq in range(20, 32):
        BP |= (1 << sq)

    return Board(WP, BP, 0)

def sq32_to_8x8(sq):
    row = sq // 4
    col = sq % 4
    if row % 2 == 0:
        return row, col * 2 + 1
    else:
        return row, col * 2

def sq8x8_to_32(row, col):
    if not (0 <= row < 8 and 0 <= col < 8):
        return None
    if (row + col) % 2 == 0:
        return None
    base = row * 4
    if row % 2 == 0:
        return base + (col // 2)
    else:
        return base + (col // 2)

def bits(bb):
    while bb:
        lsb = bb & -bb
        sq = (lsb.bit_length() - 1)
        yield sq
        bb ^= lsb

def generate_steps(board, side):
    moves = []
    pieces = board.WP if side == WHITE else board.BP
    empty = ~(board.WP | board.BP) & FULL_MASK

    for sq in bits(pieces):
        is_king = board.K & BIT[sq]

        targets = STEP_TABLE[WHITE][sq] if side == WHITE else STEP_TABLE[BLACK][sq]

        for dst in targets:
            if empty & BIT[dst]:
                moves.append((sq, dst, 0))

        # king atgal
        if is_king:
            back = STEP_TABLE[BLACK][sq] if side == WHITE else STEP_TABLE[WHITE][sq]
            for dst in back:
                if empty & BIT[dst]:
                    moves.append((sq, dst, 0))

    return moves

def generate_jumps(board, side):
    moves = []
    pieces = board.WP if side == WHITE else board.BP

    for sq in bits(pieces):
        is_king = board.K & BIT[sq]
        dfs_jumps(board, sq, sq, 0, side, is_king, moves)

    return moves

def dfs_jumps(board, start, sq, captured, side, is_king, moves):

    WP = board.WP
    BP = board.BP
    K  = board.K
    empty = ~(WP | BP) & FULL_MASK

    if side == WHITE:
        enemy = BP
        forward = JUMP_TABLE[WHITE][sq]
        back    = JUMP_TABLE[BLACK][sq]
        promote_mask = WHITE_LAST_ROW
    else:
        enemy = WP
        forward = JUMP_TABLE[BLACK][sq]
        back    = JUMP_TABLE[WHITE][sq]
        promote_mask = BLACK_LAST_ROW

    found = False

    # --- FORWARD JUMPS ---
    for mid, land in forward:

        mid_mask  = BIT[mid]
        land_mask = BIT[land]

        if (enemy & mid_mask) and (empty & land_mask):

            found = True

            undo = make_jump_inplace(board, sq, land, mid, side)

            # promotion check (no division)
            became_king = (not is_king) and (land_mask & promote_mask)

            if became_king:
                moves.append((start, land, captured | mid_mask))
            else:
                dfs_jumps(board, start, land,
                          captured | mid_mask,
                          side,
                          is_king,
                          moves)

            unmake_move(board, undo)

    # --- BACKWARD JUMPS (king only) ---
    if is_king:
        for mid, land in back:

            mid_mask  = BIT[mid]
            land_mask = BIT[land]

            if (enemy & mid_mask) and (empty & land_mask):

                found = True

                undo = make_jump_inplace(board, sq, land, mid, side)

                dfs_jumps(board, start, land,
                          captured | mid_mask,
                          side,
                          True,
                          moves)

                unmake_move(board, undo)

    if not found and captured:
        moves.append((start, sq, captured))

def make_jump_inplace(board, src, dst, mid, side):
    undo = (board.WP, board.BP, board.K)

    src_mask = BIT[src]
    dst_mask = BIT[dst]
    mid_mask = BIT[mid]

    WP = board.WP
    BP = board.BP
    K  = board.K

    if side == WHITE:
        WP ^= src_mask
        WP |= dst_mask
        BP ^= mid_mask
        K  &= ~mid_mask
        promote_mask = WHITE_LAST_ROW
    else:
        BP ^= src_mask
        BP |= dst_mask
        WP ^= mid_mask
        K  &= ~mid_mask
        promote_mask = BLACK_LAST_ROW

    if K & src_mask:
        K ^= src_mask
        K |= dst_mask
    else:
        if dst_mask & promote_mask:
            K |= dst_mask

    K &= ~src_mask
    K &= (WP | BP)

    board.WP = WP
    board.BP = BP
    board.K  = K

    return undo


def check_promotion(dst_mask, side, was_king):
    if was_king:
        return False

    if side == WHITE:
        return bool(dst_mask & WHITE_LAST_ROW)
    else:
        return bool(dst_mask & BLACK_LAST_ROW)


def generate_moves(board, side):
    jumps = generate_jumps(board, side)
    if jumps:
        return jumps
    return generate_steps(board, side)


def make_move_inplace(board, move, side):
    src, dst, captured = move

    undo = (board.WP, board.BP, board.K)

    src_mask = BIT[src]
    dst_mask = BIT[dst]

    WP = board.WP
    BP = board.BP
    K  = board.K

    if side == WHITE:
        WP ^= src_mask
        WP |= dst_mask
        BP &= ~captured
        K  &= ~captured
        promote_mask = WHITE_LAST_ROW
    else:
        BP ^= src_mask
        BP |= dst_mask
        WP &= ~captured
        K  &= ~captured
        promote_mask = BLACK_LAST_ROW

    if K & src_mask:
        K ^= src_mask
        K |= dst_mask
    else:
        if dst_mask & promote_mask:
            K |= dst_mask

    K &= ~src_mask
    K &= (WP | BP)

    board.WP = WP
    board.BP = BP
    board.K  = K

    return undo



def unmake_move(board, undo):
    board.WP, board.BP, board.K = undo

def perft(board, depth, side):
    if depth == 0:
        return 1

    moves = generate_moves(board, side)
    if not moves:
        return 1

    total = 0
    next_side = BLACK if side == WHITE else WHITE

    for move in moves:
        undo = make_move_inplace(board, move, side)
        total += perft(board, depth-1, next_side)
        unmake_move(board, undo)
    return total

def perft_divide(board, depth, side):
    moves = generate_moves(board, side)
    total = 0
    next_side = BLACK if side == WHITE else WHITE

    for move in moves:
        child = make_move(board, move, side)
        nodes = perft(child, depth - 1, next_side)
        print(move, nodes)
        total += nodes

    print("Total:", total)
    return total

def main():
    init_move_tables()
    board = start_position()

    MAX_DEPTH = 9  # pradžiai

    for depth in range(1, MAX_DEPTH + 1):
        start = time.time()
        nodes = perft(board, depth, BLACK)
        elapsed = time.time() - start

        nps = int(nodes / elapsed) if elapsed > 0 else 0

        print(f"Depth {depth}: {nodes} nodes")
        print(f"Time: {elapsed:.3f}s  NPS: {nps}")
        print("-" * 40)

if __name__ == "__main__":
    main()
