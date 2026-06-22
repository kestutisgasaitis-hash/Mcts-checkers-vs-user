import pygame
import Kreuzer_opt as kz
import random
import math
import time

kz.init_move_tables()

WHITE = kz.WHITE  # 0
BLACK = kz.BLACK  # 1

# ── Žaidėjų pusės ──
# Kreuzer: WHITE ant 0-2 eilių, juda žemyn; BLACK ant 5-7, juda aukštyn
# macaron2: Žmogus apačioje (Kreuzer WHITE), AI viršuje (Kreuzer BLACK)
HUMAN_SIDE = WHITE
AI_SIDE = BLACK

AI_TIME_BUDGET = 1.5

def lsb_index(mask: int) -> int:
    return (mask & -mask).bit_length() - 1

def is_dark(r: int, c: int) -> bool:
    return 0 <= r < 8 and 0 <= c < 8 and ((r + c) % 2 == 1)
    
def is_promotion_square(idx, side):
    r, _ = kz.sq32_to_8x8(idx)
    if side == WHITE:
        return r == 7
    else:
        return r == 0 
    
                        
class MCTSNode:
    __slots__ = ("board", "side", "parent", "move_from_parent", "children",
                 "visits", "value", "untried_moves", "_terminal_checked", "_is_terminal", "root_side")

    def __init__(self, board, side, parent=None, move_from_parent=None, root_side=None):
        self.board = board
        self.side = side
        self.parent = parent
        self.move_from_parent = move_from_parent
        self.children: list[MCTSNode] = []
        self.visits = 0
        self.value = 0.0
        self.untried_moves = None
        self._terminal_checked = False
        self._is_terminal = False
        self.root_side = root_side if root_side is not None else (parent.root_side if parent else side)

    def is_maximizing(self) -> bool:
        return self.side == self.root_side

    def _ensure_moves(self):
        if self.untried_moves is None:
            self.untried_moves = kz.generate_moves(self.board, self.side)
            self._terminal_checked = True
            self._is_terminal = (len(self.untried_moves) == 0)

    def is_terminal(self) -> bool:
        self._ensure_moves()
        return self._is_terminal

    def is_fully_expanded(self) -> bool:
        self._ensure_moves()
        return len(self.untried_moves) == 0

    def ucb_score(self, explore_c: float = 1.41) -> float:
        if self.visits == 0:
            return float("inf")

        v = self.value / self.visits

        if self.parent.side == self.root_side:
            q = v
        else:
            q = -v

        q_norm = (q + 1.0) / 2.0
        u = explore_c * math.sqrt(math.log(self.parent.visits) / self.visits)
        return q_norm + u

    def best_child(self, explore_c: float = 1.41) -> "MCTSNode":
        return max(self.children, key=lambda c: c.ucb_score(explore_c))

    def expand(self) -> "MCTSNode":
        self._ensure_moves()
        if not self.untried_moves:
            return self
        i = random.randrange(len(self.untried_moves))
        move = self.untried_moves.pop(i)
        child_board = self.board.copy()        
        kz.make_move_inplace(child_board, move, self.side)      
        child_side = self.side ^ 1
        child = MCTSNode(child_board, child_side, parent=self, move_from_parent=move, root_side=self.root_side)
        self.children.append(child)
        return child

    def backpropagate(self, result: float):
        node = self
        while node is not None:
            node.visits += 1
            node.value += result
            node = node.parent


def mcts_search(root_board, root_side, time_budget: float = 3.0):
    root = MCTSNode(root_board, root_side, root_side=root_side)

    moves = kz.generate_moves(root_board, root_side)
    if not moves:
        return None, root_side, {}
    if len(moves) == 1:
        child_board = root_board.copy()
        kz.make_move_inplace(child_board, moves[0], root_side)
        return child_board, root_side ^ 1, {"iterations": 1, "elapsed": 0.0, "rps": 0, "win_rate": 50.0, "children": []}

    t0 = time.perf_counter()
    iterations = 0
    check_interval = 64

    while True:
        if (iterations & 63) == 0 and time.perf_counter() - t0 >= time_budget:
            break
        node = root
        while not node.is_terminal() and node.is_fully_expanded():
            node = node.best_child(0.7)
        if not node.is_terminal() and not node.is_fully_expanded():
            node = node.expand()
        result = rollout(node.board, node.side, root_side)
        node.backpropagate(result)
        iterations += 1

    elapsed = time.perf_counter() - t0
    rps = iterations / elapsed if elapsed > 0 else 0.0

    best = None
    max_visits = -1
    for c in root.children:
        if c.visits > max_visits:
            max_visits = c.visits
            best = c
    if best is None:
        best = root.children[0]

    best_val = (best.value / best.visits) if best.visits > 0 else 0.0

    print(f"MCTS Results (Iters: {iterations}, RPS: {rps:.0f}):")
    children_stats = []
    sorted_children = sorted(root.children, key=lambda x: x.visits, reverse=True)

    for i, c in enumerate(sorted_children):
        avg_val = (c.value / c.visits) if c.visits else 0.0
        win_rate = (avg_val + 1.0) / 2.0 * 100.0
        children_stats.append({"visits": c.visits, "win_rate": win_rate})
        print(f"  Child #{i+1}: Visits: {c.visits:4d}, WinRate: {win_rate:5.1f}%")

    best_win_rate = (best_val + 1.0) / 2.0 * 100.0
    stats = {
        "iterations": iterations,
        "elapsed": elapsed,
        "rps": rps,
        "win_rate": best_win_rate,
        "children": children_stats[:8],
    }

    print(f"Chosen: Visits: {best.visits}, WinRate:{best_win_rate:.1f}%")

    return best.board, best.side, stats

def rollout(board: kz.Board, side: int, root_side: int) -> float:
    current = board.copy()
    current_side = side

    depth = 0
    max_depth = random.randint(28, 32)
    qmc = 0
    qmc_limit = 10

    while depth < max_depth:

        moves = kz.generate_moves(current, current_side)

        if not moves:
            return -1.0 if current_side == root_side else 1.0

        weights = []
        for m in moves:
            if is_promotion_move(current, m, current_side):
                weights.append(2.5)
            else:
                weights.append(1.0)

        move = random.choices(moves, weights=weights, k=1)[0]

        is_quiet = (move[2] == 0) and (not is_promotion_move(current, move, current_side))

        kz.make_move_inplace(current, move, current_side)
        current_side ^= 1
        depth += 1

        if is_quiet:
            qmc += 1
        else:
            qmc = 0

        if qmc >= qmc_limit:
            break

    return evaluate_rollout_board(current, root_side)    
     
def evaluate_rollout_board(board, root_side):
    wm = (board.WP & ~board.K).bit_count()
    wk = (board.WP & board.K).bit_count()
    bm = (board.BP & ~board.K).bit_count()
    bk = (board.BP & board.K).bit_count()

    white_score = wm + 1.6 * wk
    black_score = bm + 1.6 * bk

    white_men = board.WP & ~board.K
    black_men = board.BP & ~board.K

    white_adv = 0
    black_adv = 0

    center_diff = 0

    for i in range(32):
        bit = 1 << i

        if white_men & bit:
            r, c = kz.sq32_to_8x8(i)
            white_adv += r
            center_diff += (3.5 - abs(c - 3.5))

        elif black_men & bit:
            r, c = kz.sq32_to_8x8(i)
            black_adv += (7 - r)
            center_diff -= (3.5 - abs(c - 3.5))

    white_score += 0.05 * white_adv
    black_score += 0.05 * black_adv

    # SYMMETRIC center application
    white_score += 0.02 * center_diff
    black_score -= 0.02 * center_diff

    diff = white_score - black_score

    if root_side == BLACK:
        diff = -diff

    return math.tanh(0.25 * diff)


def is_promotion_move(board, move, side):
    src, dst, captured = move

    src_mask = kz.BIT[src]
    dst_mask = kz.BIT[dst]

    # jei jau buvo king, promotion nėra
    if board.K & src_mask:
        return False

    if side == WHITE:
        return bool(dst_mask & kz.WHITE_LAST_ROW)
    else:
        return bool(dst_mask & kz.BLACK_LAST_ROW)

def rc_to_legal_targets(board, side, r, c):
    if (r + c) % 2 == 0:
        return []

    idx = kz.sq8x8_to_32(r, c)
    if idx is None:
        return []

    own = board.WP if side == kz.WHITE else board.BP
    if not (own & (1 << idx)):
        return []

    targets = []
    for move in kz.generate_moves(board, side):
        src, dst, _ = move
        if src == idx:
            tr, tc = kz.sq32_to_8x8(dst)
            targets.append((tr, tc))
    return targets

def find_child_for_move(board, side, from_rc, to_rc):
    from_idx = kz.sq8x8_to_32(*from_rc)
    to_idx = kz.sq8x8_to_32(*to_rc)

    for move in kz.generate_moves(board, side):
        src, dst, _ = move
        if src == from_idx and dst == to_idx:
            child = board.copy()     
            kz.make_move_inplace(child, move, side)
            return child, side ^ 1

    return None

def pos_to_board_array(board: kz.Board):
    arr = [[0]*8 for _ in range(8)]
    for i in range(32):
        r, c = kz.sq32_to_8x8(i)
        mask = 1 << i
        if board.WP & mask:
            arr[r][c] = "bk" if board.K & mask else "bm"
        elif board.BP & mask:
            arr[r][c] = "rk" if board.K & mask else "rm"
    return arr
    
SQ_SIZE = 80
BOARD_PX = SQ_SIZE * 8
STATS_H = 140
WIN_W = BOARD_PX
WIN_H = BOARD_PX + STATS_H

COLOR_LIGHT = (240, 217, 181)
COLOR_DARK = (181, 136, 99)
COLOR_BLACK_PIECE = (30, 30, 30)
COLOR_WHITE_PIECE = (230, 230, 230)
COLOR_KING_DOT = (200, 50, 50)
COLOR_BG_STATS = (40, 40, 40)
COLOR_TEXT = (220, 220, 220)
COLOR_TEXT_BRIGHT = (100, 255, 100)

def flip_r(r):
    return 7 - r

def flip_c(c):
    return 7 - c

def draw_board(screen, board, selected_sq=None, legal_targets=None):
    arr = pos_to_board_array(board)

    for r in range(8):
        for c in range(8):
            dr = flip_r(r)
            dc = flip_c(c)
            x = dc * SQ_SIZE
            y = dr * SQ_SIZE

            dark = ((r + c) % 2 == 1)
            color = COLOR_DARK if dark else COLOR_LIGHT
            pygame.draw.rect(screen, color, (x, y, SQ_SIZE, SQ_SIZE))

            if selected_sq and selected_sq == (r, c):
                s = pygame.Surface((SQ_SIZE, SQ_SIZE), pygame.SRCALPHA)
                s.fill((255, 255, 0, 100))
                screen.blit(s, (x, y))

            if legal_targets and (r, c) in legal_targets:
                s = pygame.Surface((SQ_SIZE, SQ_SIZE), pygame.SRCALPHA)
                s.fill((0, 255, 0, 90))
                screen.blit(s, (x, y))

            piece = arr[r][c]
            if piece:
                center = (x + SQ_SIZE // 2, y + SQ_SIZE // 2)
                radius = SQ_SIZE // 2 - 8

                if piece in ("rm", "rk"):
                    pygame.draw.circle(screen, COLOR_WHITE_PIECE, center, radius)
                    pygame.draw.circle(screen, (80, 80, 80), center, radius, 2)
                    if piece == "rk":
                        pygame.draw.circle(screen, COLOR_KING_DOT, center, 10)
                else:
                    pygame.draw.circle(screen, COLOR_BLACK_PIECE, center, radius)
                    pygame.draw.circle(screen, (220, 220, 220), center, radius, 2)
                    if piece == "bk":
                        pygame.draw.circle(screen, COLOR_KING_DOT, center, 10)   

def _format_stats(stats):
    if not stats:
        return [
            "Macaron Checkers",
            "No AI stats yet",
            "You: bottom side",
            "AI: top side"
        ]

    return [
        f"Iterations: {stats.get('iterations', 0)}",
        f"RPS: {stats.get('rps', 0):.0f}",
        f"Win rate: {stats.get('win_rate', 0):.1f}%",
        "R = restart"
    ]


def draw_stats(screen, font, stats):
    pygame.draw.rect(screen, COLOR_BG_STATS, (0, BOARD_PX, WIN_W, STATS_H))
    lines = _format_stats(stats)
    y = BOARD_PX + 12
    for line in lines:
        surf = font.render(line, True, COLOR_TEXT_BRIGHT if "Win rate" in line else COLOR_TEXT)
        screen.blit(surf, (12, y))
        y += 28

    
def main():
    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.init()
    pygame.display.init()
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("Macaron Checkers")
    clock = pygame.time.Clock()
    pygame.font.init()
    font = pygame.font.SysFont(None, 28)
    pygame.mixer.init()
    move_sound = pygame.mixer.Sound("Move.mp3")

    board = kz.start_position()
    side = HUMAN_SIDE

    selected_sq = None
    legal_targets = []
    stats = {}
    running = True
    pygame.key.start_text_input()
    while running:
        human_has_moves = bool(kz.generate_moves(board, side)) if side == HUMAN_SIDE else True
        ai_has_moves = bool(kz.generate_moves(board, side)) if side == AI_SIDE else True

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    board = kz.start_position()
                    side = HUMAN_SIDE
                    selected_sq = None
                    legal_targets = []
                    stats = {}
                elif event.key == pygame.K_q:
                	running = False

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if side != HUMAN_SIDE:
                    continue

                mx, my = pygame.mouse.get_pos()
                if my >= BOARD_PX:
                    continue

                dc = mx // SQ_SIZE
                dr = my // SQ_SIZE
                r = flip_r(dr)
                c = flip_c(dc)

                if not is_dark(r, c):
                    selected_sq = None
                    legal_targets = []
                    continue

                if selected_sq and (r, c) in legal_targets:
                    result = find_child_for_move(board, side, selected_sq, (r, c))
                    if result is not None:
                        board, side = result
                    selected_sq = None
                    legal_targets = []
                    draw_board(screen, board, selected_sq, legal_targets)
                    draw_stats(screen, font, stats)
                    pygame.display.flip()
                    continue

                idx = kz.sq8x8_to_32(r, c)
                if idx is not None and (board.WP & (1 << idx)):
                    selected_sq = (r, c)
                    legal_targets = rc_to_legal_targets(board, side, r, c)
                else:
                    selected_sq = None
                    legal_targets = []

        if side == AI_SIDE:
            moves = kz.generate_moves(board, side)
            if moves:
                new_board, new_side, stats = mcts_search(board, side, AI_TIME_BUDGET)
                if new_board is not None:
                    board = new_board
                    side = new_side
                    move_sound.play()

        draw_board(screen, board, selected_sq, legal_targets)
        draw_stats(screen, font, stats)

        if side == HUMAN_SIDE and not human_has_moves:
            msg = font.render("No legal moves for you. Press R to restart.", True, (255, 80, 80))
            screen.blit(msg, (12, BOARD_PX + 118))

        if side == AI_SIDE and not ai_has_moves:
            msg = font.render("AI has no legal moves. Press R to restart.", True, (80, 255, 80))
            screen.blit(msg, (12, BOARD_PX + 118))

        pygame.display.flip()
        clock.tick(60)
    pygame.stop_text_input()
    pygame.display.quit()
    pygame.quit()


if __name__ == "__main__":
    main()            
                    
    




