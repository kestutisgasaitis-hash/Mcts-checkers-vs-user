"""
Checkers game with Pygame GUI and MCTS AI - refactored version.
Features:
- Bitboard-optimized Position class
- MCTS AI with status bar feedback (Win%, RPS, Time)
- Official 1-32 notation display in cell corners
"""
from dataclasses import dataclass
from typing import List, Tuple, Optional
import pygame
import time
import math
import random

WHITE = 0
BLACK = 1

# Build mappings between 8x8 board coordinates and 32-square indices
_SQ_TO_RC = [None] * 32
_RC_TO_SQ = [[-1] * 8 for _ in range(8)]

_sq = 0
for r in range(8):
    for c in range(8):
        if (r + c) % 2 == 1:
            _SQ_TO_RC[_sq] = (r, c)
            _RC_TO_SQ[r][c] = _sq
            _sq += 1

def rc_to_sq(r: int, c: int) -> int:
    if 0 <= r < 8 and 0 <= c < 8:
        return _RC_TO_SQ[r][c]
    return -1

def sq_to_rc(sq: int) -> Tuple[int, int]:
    return _SQ_TO_RC[sq]

# Neighbor arrays for movement
NW = [-1] * 32
NE = [-1] * 32
SW = [-1] * 32
SE = [-1] * 32

for sq in range(32):
    r, c = sq_to_rc(sq)
    NW[sq] = rc_to_sq(r - 1, c - 1)
    NE[sq] = rc_to_sq(r - 1, c + 1)
    SW[sq] = rc_to_sq(r + 1, c - 1)
    SE[sq] = rc_to_sq(r + 1, c + 1)

WHITE_PROMOTION = set(i for i in range(32) if sq_to_rc(i)[0] == 0)
BLACK_PROMOTION = set(i for i in range(32) if sq_to_rc(i)[0] == 7)

def bit(sq: int) -> int:
    return 1 << sq

def internal_to_off(sq0: int) -> int:
    """Converts internal 0-31 index to official 1-32 notation."""
    if not (0 <= sq0 < 32):
        raise ValueError("internal square out of range")
    return 32 - sq0

def off_to_internal(off: int) -> int:
    """Converts official 1-32 notation to internal 0-31 index."""
    if not (1 <= off <= 32):
        raise ValueError("official square out of range")
    return 32 - off

@dataclass(slots=True)
class Move:
    start: int
    path: List[int]
    captured: List[int]
    promote: bool = False

    def is_capture(self) -> bool:
        return len(self.captured) > 0

    def __str__(self) -> str:
        sep = "x" if self.is_capture() else "-"
        numbers = [internal_to_off(self.start)] + [internal_to_off(sq) for sq in self.path]
        notation = sep.join(str(n) for n in numbers)
        if self.promote:
            notation += " (promote)"
        return notation

class Position:
    __slots__ = ("white_men",  "white_kings", "black_men", "black_kings","side","moves_without_capture")
    def __init__(self, white_men: int, white_kings: int, black_men: int, black_kings: int, side: int = WHITE, moves_without_capture: int = 0):
        self.white_men = white_men
        self.white_kings = white_kings
        self.black_men = black_men
        self.black_kings = black_kings
        self.side = side
        self.moves_without_capture = moves_without_capture

    @staticmethod
    def starting_position() -> "Position":
        black, white = 0, 0
        for sq in range(32):
            r, _ = sq_to_rc(sq)
            if r <= 2: black |= bit(sq)
            elif r >= 5: white |= bit(sq)
        return Position(white, 0, black, 0, WHITE, 0)

    def occupied(self) -> int:
        return self.white_men | self.white_kings | self.black_men | self.black_kings

    def own_men(self) -> int: return self.white_men if self.side == WHITE else self.black_men
    def own_kings(self) -> int: return self.white_kings if self.side == WHITE else self.black_kings
    def opp_men(self) -> int: return self.black_men if self.side == WHITE else self.white_men
    def opp_kings(self) -> int: return self.black_kings if self.side == WHITE else self.white_kings

    def make_move(self, move: Move) -> "Position":
        new_w_m, new_w_k = self.white_men, self.white_kings
        new_b_m, new_b_k = self.black_men, self.black_kings
        from_bit, to_bit = bit(move.start), bit(move.path[-1])
        
        # Remove piece from start
        if self.side == WHITE:
            if (new_w_k & from_bit): new_w_k &= ~from_bit
            else: new_w_m &= ~from_bit
        else:
            if (new_b_k & from_bit): new_b_k &= ~from_bit
            else: new_b_m &= ~from_bit

        # Handle captures
        for csq in move.captured:
            c_bit = ~bit(csq)
            new_w_m &= c_bit; new_w_k &= c_bit; new_b_m &= c_bit; new_b_k &= c_bit

        # Place piece at destination
        if self.side == WHITE:
            if move.promote or (self.white_kings & from_bit): new_w_k |= to_bit
            else: new_w_m |= to_bit
        else:
            if move.promote or (self.black_kings & from_bit): new_b_k |= to_bit
            else: new_b_m |= to_bit

        return Position(new_w_m, new_w_k, new_b_m, new_b_k, 1-self.side, 
                        0 if (move.is_capture() or move.promote) else self.moves_without_capture + 1)

    def generate_moves(self) -> List[Move]:
        caps = self._generate_captures()
        return caps if caps else self._generate_quiet_moves()

    def _generate_quiet_moves(self) -> List[Move]:
        moves, occ = [], self.occupied()
        m, k = self.own_men(), self.own_kings()
        m_dirs = [NW, NE] if self.side == WHITE else [SW, SE]
        while m:
            sq = (m & -m).bit_length() - 1
            m &= m - 1
            for D in m_dirs:
                to = D[sq]
                if to != -1 and not ((occ >> to) & 1):
                    moves.append(Move(sq, [to], [], to in (WHITE_PROMOTION if self.side == WHITE else BLACK_PROMOTION)))
        while k:
            sq = (k & -k).bit_length() - 1
            k &= k - 1
            for D in (NW, NE, SW, SE):
                to = D[sq]
                if to != -1 and not ((occ >> to) & 1):
                    moves.append(Move(sq, [to], [], False))
        return moves

    def _generate_captures(self) -> List[Move]:
        opp = self.opp_men() | self.opp_kings()
        all_caps = []
        
        def recurse(start, curr, is_k, occ, path, caps, visited_caps):
            found = False
            dirs = (NW, NE, SW, SE) if is_k else ([NW, NE] if self.side == WHITE else [SW, SE])
            for D in dirs:
                mid, land = D[curr], D[D[curr]] if D[curr] != -1 else -1
                if mid != -1 and land != -1 and (opp & bit(mid)) and not (occ & bit(land)) and not (visited_caps & bit(mid)):
                    found = True
                    if not is_k and (land in (WHITE_PROMOTION if self.side == WHITE else BLACK_PROMOTION)):
                        all_caps.append(Move(start, path + [land], caps + [mid], True))
                    else:
                        recurse(start, land, is_k, (occ & ~bit(curr)) | bit(land), path + [land], caps + [mid], visited_caps | bit(mid))
            if not found and path: all_caps.append(Move(start, path, caps, False))
        m, k = self.own_men(), self.own_kings()
        while m:
            sq = (m & -m).bit_length() - 1
            m &= m - 1
            recurse(sq, sq, False, self.occupied(), [], [], 0)
        while k:
            sq = (k & -k).bit_length() - 1
            k &= k - 1
            recurse(sq, sq, True, self.occupied(), [], [], 0)
        return all_caps

    def is_terminal(self) -> bool: return len(self.generate_moves()) == 0
    def get_winner(self) -> Optional[int]:
        return BLACK if self.side == WHITE else WHITE if self.is_terminal() else None

# --- MCTS core ---
class TreeNode:
    __slots__ = ("position",  "parent", "M", "V","children", "move","untried_moves")
    def __init__(self, position: Position, parent=None,move=None):
        self.position = position
        self.parent = parent
        self.M = 0.0
        self.V = 0
        self.children = []
        self.move = move
        self.untried_moves = position.generate_moves()
        random.shuffle(self.untried_moves)

# --- Main search function ---
def mcts_search(root_position:Position,num_rounds:int,time_budget:float):
    root = TreeNode(root_position)
    t0 = time.perf_counter()
    sims = 0
    for _ in range(num_rounds):
        if (sims & 63 ) == 0 and time.perf_counter() - t0 >= time_budget:
            break
        # Selection
        node = root
        while not node.untried_moves and node.children:
            node = max(node.children, key=lambda n: (n.M/n.V if n.parent.position.side==WHITE else 1-(n.M/n.V)) + 0.7*math.sqrt(math.log(n.parent.V)/n.V))
            
        #  Expansion
        if node.untried_moves:
            move = node.untried_moves.pop()
            child = TreeNode(node.position.make_move(move), parent=node,move=move)
            node.children.append(child)
            node = child
        
        # Simulation
        curr = node.position
        #max_depth = random.randint( 28, 30)
        for _ in range(32):
            moves = curr.generate_moves()
            if not moves: payout = 1.0 if curr.side == BLACK else 0.0; break
            curr = curr.make_move(random.choice(moves))
            if curr.moves_without_capture >= 10: # 6-12
                payout = 0.5
                break
        else: payout = 0.5
        
        # Backpropagation
        while node: node.V += 1; node.M += payout; node = node.parent
        sims += 1

    elapsed = time.perf_counter() -  t0
    sorted_children = sorted(root.children, key=lambda n: n.V, reverse=True)
    print(f"\n--- AI MCTS Analysis (Rounds: {sims}, Time: {elapsed:.3f}s) ---")
    for i, child in enumerate(sorted_children[:5]):
        win_rate = child.M / child.V if root_position.side == WHITE else 1 - (child.M / child.V)
        print(f"{i+1}. Move: {child.move} | Visits: {child.V} | Win Rate: {win_rate:.2%}")
    print("-" * 50)
    best_child = max(root.children, key=lambda n: n.V)
    win_rate = best_child.M/best_child.V if root_position.side==WHITE else 1-(best_child.M/best_child.V)
    return best_child.move, {"win_rate": win_rate, "rps": int(sims/elapsed), "time": elapsed}

# --- GUI Implementation ---
class CheckersGUI:
    def __init__(self, mcts_rounds=0,mcts_time=0):
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.init()
        pygame.display.init()
        self.SQUARE_SIZE = 75
        self.BOARD_SIZE = 600
        self.STATUS_HEIGHT = 60
        self.move_sound = pygame.mixer.Sound("Move.mp3")
        pygame.mixer.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode((self.BOARD_SIZE, self.BOARD_SIZE + self.STATUS_HEIGHT))
        pygame.display.set_caption("Checkers MCTS (Bitboard Optimized)")
        
        self.font_main = pygame.font.SysFont("Arial", 16, bold=True)
        self.font_small = pygame.font.SysFont("Consolas", 14)
        self.font_index = pygame.font.SysFont("Arial", 12, bold=True)
        
        self.position = Position.starting_position()
        self.selected_sq = None
        self.legal_moves_from_selected = []
        
        self.mcts_rounds = mcts_rounds
        self.mcts_time = mcts_time
        
        self.game_over = False
        self.last_stats = {"win_rate": 0.0, "rps": 0, "status": "Your Turn (White)", "last_move": "None", "time": 0.0}

    def reset_game(self):
        self.position = Position.starting_position()
        self.selected_sq = None
        self.legal_moves_from_selected = []
        self.game_over = False
        self.last_stats = {"win_rate": 0.0, "rps": 0, "status": "Your Turn (White)", "last_move": "None", "time": 0.0}

    def draw_status_bar(self):
        pygame.draw.rect(self.screen, (30, 30, 30), (0, self.BOARD_SIZE, self.BOARD_SIZE, self.STATUS_HEIGHT))
        pygame.draw.line(self.screen, (80, 80, 80), (0, self.BOARD_SIZE), (self.BOARD_SIZE, self.BOARD_SIZE), 2)
        
        # Main status
        status = "GAME OVER" if self.game_over else self.last_stats["status"]
        line1 = f"{status} | Last AI Move: {self.last_stats['last_move']}"
        
        # Statistics
        line2 = f"Win Prob: {self.last_stats['win_rate']:.1%} | RPS: {self.last_stats['rps']} | Time: {self.last_stats['time']:.3f}s"
        
        # Control remainder
        line3 = "Controls: [R] Reset Game | [Q] Quit Game"
        
        # Drawing on screen
        self.screen.blit(self.font_main.render(line1, True, (255, 255, 255)), (15, self.BOARD_SIZE + 5))
        self.screen.blit(self.font_small.render(line2, True, (180, 180, 180)), (15, self.BOARD_SIZE + 25))
        self.screen.blit(self.font_small.render(line3, True, (180, 200, 220)), (15, self.BOARD_SIZE + 42))

    def draw_board(self):
        for r in range(8):
            for c in range(8):
                x, y = c * self.SQUARE_SIZE, r * self.SQUARE_SIZE
                sq = rc_to_sq(r, c)
                
                # Background drawing
                color = (240, 217, 181) if (r + c) % 2 == 0 else (119, 148, 85)
                pygame.draw.rect(self.screen, color, (x, y, self.SQUARE_SIZE, self.SQUARE_SIZE))

                # 1. Selected piece highlight (Yellow frame)
                if sq == self.selected_sq:
                    pygame.draw.rect(self.screen, (255, 255, 0), (x, y, self.SQUARE_SIZE, self.SQUARE_SIZE), 5)

                # 2. Possible moves highlights  (Yellow dots)
                if any(m.path[-1] == sq for m in self.legal_moves_from_selected):
                    pygame.draw.circle(self.screen, (255, 255, 0), (x + self.SQUARE_SIZE//2, y + self.SQUARE_SIZE//2), 12)

                if (r + c) % 2 == 1:
                    # Numbers drawing
                    idx_text = self.font_index.render(str(internal_to_off(sq)), True, (180, 200, 220))
                    self.screen.blit(idx_text, (x + self.SQUARE_SIZE - idx_text.get_width() - 4, y + 4))

                    # Drawing pieces
                    p_color, is_king = None, False
                    if (self.position.white_men >> sq) & 1: 
                        p_color = (255, 255, 255)
                        outline_color = (100, 100, 100) # Outline for white
                    elif (self.position.white_kings >> sq) & 1: 
                        p_color, is_king = (255, 255, 255), True
                        outline_color = (100, 100, 100)
                    elif (self.position.black_men >> sq) & 1: 
                        p_color = (40, 40, 40)
                        outline_color = (100, 100, 100) # Outline for black
                    elif (self.position.black_kings >> sq) & 1: 
                        p_color, is_king = (40, 40, 40), True
                        outline_color = (100, 100, 100)
                    
                    if p_color:
                        # 1. Outline ( bigger circle)
                        pygame.draw.circle(self.screen, outline_color, (x+37, y+37), 32)
                        # 2. Main piece
                        pygame.draw.circle(self.screen, p_color, (x+37, y+37), 28)
                        # 3. King( if  needed)
                        if is_king: 
                            pygame.draw.circle(self.screen, (255, 215, 0), (x+37, y+37), 12, 4)
     
        self.draw_status_bar()

    def run(self):
        pygame.key.start_text_input()
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT: pygame.quit(); return
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_r:
                        self.reset_game()
                    elif event.key == pygame.K_q:
                    	pygame.key.stop_text_input()
                    	pygame.display.quit()
                    	pygame.quit()
                    	return
                if event.type == pygame.MOUSEBUTTONDOWN and not self.game_over and self.position.side == WHITE:
                    c, r = event.pos[0]//self.SQUARE_SIZE, event.pos[1]//self.SQUARE_SIZE
                    if r < 8:
                        sq = rc_to_sq(r, c)
                        if sq != -1:
                            # If clicked own piece
                            if (self.position.own_men() | self.position.own_kings()) & bit(sq):
                                self.selected_sq = sq
                                self.legal_moves_from_selected = [m for m in self.position.generate_moves() if m.start == sq]
                            # If clicked valid destination square
                            elif self.selected_sq is not None:
                                move_made = False
                                for m in self.legal_moves_from_selected:
                                    if m.path[-1] == sq:
                                        self.position = self.position.make_move(m)
                                        move_made = True
                                        break
                                self.selected_sq = None
                                self.legal_moves_from_selected = []
                                if move_made and self.position.is_terminal(): self.game_over = True
                            else:
                                self.selected_sq = None
                                self.legal_moves_from_selected = []
            
            # AI move logic
            if not self.game_over and self.position.side == BLACK:
                self.last_stats["status"] = "AI is thinking..."
                self.draw_board()
                pygame.display.flip()
                move, stats = mcts_search(self.position, self.mcts_rounds,self.mcts_time)
                self.move_sound.play()
                self.last_stats.update({"win_rate": stats["win_rate"], "rps": stats["rps"], "time": stats["time"], "last_move": str(move), "status": "Your Turn (White)"})
                self.position = self.position.make_move(move)
                if self.position.is_terminal(): self.game_over = True
            
            self.draw_board()
            pygame.display.flip()
            pygame.time.Clock().tick(30)
        pygame.key.stop_text_input()
        pygame.display.quit()
        pygame.quit()

if __name__ == "__main__":
    CheckersGUI(10000,2.0).run() # let 2 sec per move
    
    
    
    
