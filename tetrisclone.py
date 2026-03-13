#!/usr/bin/env python3
"""
Tetris Clone - A classic Tetris game implemented in Python using pygame.
Controls: Arrow keys to move, Up to rotate, Space for hard drop, P to pause, Esc to quit.
"""

import pygame
import random
import sys

# Initialize pygame
pygame.init()

# Game constants
BLOCK_SIZE = 30
GRID_WIDTH = 10
GRID_HEIGHT = 20
SIDEBAR_WIDTH = 200
SCREEN_WIDTH = GRID_WIDTH * BLOCK_SIZE + SIDEBAR_WIDTH
SCREEN_HEIGHT = GRID_HEIGHT * BLOCK_SIZE

# Colors (R, G, B)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRAY = (128, 128, 128)
DARK_GRAY = (40, 40, 40)

# Tetromino colors
COLORS = {
    'I': (0, 255, 255),   # Cyan
    'O': (255, 255, 0),   # Yellow
    'T': (128, 0, 128),   # Purple
    'S': (0, 255, 0),     # Green
    'Z': (255, 0, 0),     # Red
    'J': (0, 0, 255),     # Blue
    'L': (255, 165, 0)    # Orange
}

# Tetromino shapes (4 rotations each)
SHAPES = {
    'I': [
        [(0, 1), (1, 1), (2, 1), (3, 1)],
        [(2, 0), (2, 1), (2, 2), (2, 3)],
        [(0, 2), (1, 2), (2, 2), (3, 2)],
        [(1, 0), (1, 1), (1, 2), (1, 3)]
    ],
    'O': [
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)]
    ],
    'T': [
        [(1, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (1, 2)],
        [(1, 0), (0, 1), (1, 1), (1, 2)]
    ],
    'S': [
        [(1, 0), (2, 0), (0, 1), (1, 1)],
        [(1, 0), (1, 1), (2, 1), (2, 2)],
        [(1, 1), (2, 1), (0, 2), (1, 2)],
        [(0, 0), (0, 1), (1, 1), (1, 2)]
    ],
    'Z': [
        [(0, 0), (1, 0), (1, 1), (2, 1)],
        [(2, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (1, 2), (2, 2)],
        [(1, 0), (0, 1), (1, 1), (0, 2)]
    ],
    'J': [
        [(0, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (2, 2)],
        [(1, 0), (1, 1), (0, 2), (1, 2)]
    ],
    'L': [
        [(2, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (1, 2), (2, 2)],
        [(0, 1), (1, 1), (2, 1), (0, 2)],
        [(0, 0), (1, 0), (1, 1), (1, 2)]
    ]
}

class Tetromino:
    def __init__(self):
        self.type = random.choice(list(SHAPES.keys()))
        self.shape = SHAPES[self.type][0]
        self.color = COLORS[self.type]
        self.x = GRID_WIDTH // 2 - 1
        self.y = 0

    def rotate(self):
        """Rotate the piece clockwise"""
        index = (SHAPES[self.type].index(self.shape) + 1) % 4
        self.shape = SHAPES[self.type][index]


class TetrisGame:
    def __init__(self):
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("Tetris Clone")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 36)
        self.small_font = pygame.font.Font(None, 24)
        self.reset_game()

    def reset_game(self):
        """Reset game state"""
        self.grid = [[None for _ in range(GRID_WIDTH)] for _ in range(GRID_HEIGHT)]
        self.current_piece = Tetromino()
        self.next_piece = Tetromino()
        self.score = 0
        self.lines_cleared = 0
        self.level = 1
        self.game_over = False
        self.paused = False
        self.drop_time = 0
        self.drop_interval = 500  # milliseconds

    def valid_position(self, piece, offset_x=0, offset_y=0):
        """Check if the piece is in a valid position"""
        for x, y in piece.shape:
            new_x = piece.x + x + offset_x
            new_y = piece.y + y + offset_y
            # Check boundaries and collisions
            if new_x < 0 or new_x >= GRID_WIDTH or new_y >= GRID_HEIGHT:
                return False
            if new_y >= 0 and self.grid[new_y][new_x]:
                return False
        return True

    def lock_piece(self):
        """Lock the current piece into the grid"""
        for x, y in self.current_piece.shape:
            grid_y = self.current_piece.y + y
            if grid_y >= 0:
                self.grid[grid_y][x] = self.current_piece.color
        
        # Check for completed lines
        self.clear_lines()

        # Spawn new piece
        self.current_piece = self.next_piece
        self.next_piece = Tetromino()

        # Check game over
        if not self.valid_position(self.current_piece):
            self.game_over = True

    def clear_lines(self):
        """Clear completed lines and update score"""
        lines_to_clear = []
        for y in range(GRID_HEIGHT):
            if all(self.grid[y]):
                lines_to_clear.append(y)

        for y in lines_to_clear:
            del self.grid[y]
            self.grid.insert(0, [None for _ in range(GRID_WIDTH)])

        num_lines = len(lines_to_clear)
        if num_lines > 0:
            # Score based on number of lines cleared at once
            scores = {1: 100, 2: 300, 3: 500, 4: 800}
            self.score += scores.get(num_lines, 0) * self.level
            self.lines_cleared += num_lines
            
            # Level up every 10 lines
            self.level = self.lines_cleared // 10 + 1
            self.drop_interval = max(50, 500 - (self.level - 1) * 50)

    def draw_block(self, x, y, color):
        """Draw a single block"""
        rect = pygame.Rect(x * BLOCK_SIZE, y * BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE)
        pygame.draw.rect(self.screen, color, rect)
        # Add bevel effect
        pygame.draw.rect(self.screen, tuple(min(255, c + 40) for c in color), 
                        (rect.x, rect.y, rect.width - 1, rect.height - 1), 2)

    def draw_grid(self):
        """Draw the game grid"""
        # Draw background
        pygame.draw.rect(self.screen, DARK_GRAY, 
                        (0, 0, GRID_WIDTH * BLOCK_SIZE, SCREEN_HEIGHT))
        
        # Draw grid lines
        for x in range(GRID_WIDTH + 1):
            pygame.draw.line(self.screen, GRAY, 
                           (x * BLOCK_SIZE, 0), 
                           (x * BLOCK_SIZE, SCREEN_HEIGHT))
        for y in range(GRID_HEIGHT + 1):
            pygame.draw.line(self.screen, GRAY, 
                           (0, y * BLOCK_SIZE), 
                           (GRID_WIDTH * BLOCK_SIZE, y * BLOCK_SIZE))

    def draw_piece(self, piece, offset_x=0, offset_y=0):
        """Draw a tetromino piece"""
        for x, y in piece.shape:
            self.draw_block(piece.x + x + offset_x, piece.y + y + offset_y, piece.color)

    def draw_board(self):
        """Draw the game board including locked pieces and current piece"""
        # Draw locked pieces
        for y in range(GRID_HEIGHT):
            for x in range(GRID_WIDTH):
                if self.grid[y][x]:
                    self.draw_block(x, y, self.grid[y][x])

        # Draw ghost piece (where the piece will land)
        if not self.game_over:
            ghost_y = 0
            while self.valid_position(self.current_piece, offset_y=ghost_y + 1):
                ghost_y += 1
            for x, y in self.current_piece.shape:
                pygame.draw.rect(self.screen, 
                               tuple(c // 2 for c in self.current_piece.color),
                               (self.current_piece.x + x) * BLOCK_SIZE,
                               (self.current_piece.y + y + ghost_y) * BLOCK_SIZE,
                               BLOCK_SIZE - 1, 1)

        # Draw current piece
        if not self.game_over:
            self.draw_piece(self.current_piece)

    def draw_sidebar(self):
        """Draw the sidebar with score and next piece"""
        sidebar_x = GRID_WIDTH * BLOCK_SIZE
        
        # Background
        pygame.draw.rect(self.screen, DARK_GRAY, 
                        (sidebar_x, 0, SIDEBAR_WIDTH, SCREEN_HEIGHT))
        
        y_offset = 20
        
        # Title
        title = self.font.render("TETRIS", True, WHITE)
        self.screen.blit(title, (sidebar_x + 50, y_offset))
        y_offset += 60

        # Next piece
        next_text = self.small_font.render("NEXT:", True, WHITE)
        self.screen.blit(next_text, (sidebar_x + 20, y_offset))
        y_offset += 40
        
        # Draw next piece preview
        for x, y in self.next_piece.shape:
            rect_x = sidebar_x + 30 + x * BLOCK_SIZE // 2
            rect_y = y_offset + y * BLOCK_SIZE // 2
            pygame.draw.rect(self.screen, self.next_piece.color,
                           (rect_x, rect_y, BLOCK_SIZE // 2 - 1, BLOCK_SIZE // 2 - 1))
        y_offset += 80

        # Score
        score_text = self.small_font.render("SCORE:", True, WHITE)
        self.screen.blit(score_text, (sidebar_x + 20, y_offset))
        y_offset += 30
        score_val = self.font.render(str(self.score), True, WHITE)
        self.screen.blit(score_val, (sidebar_x + 40, y_offset))
        y_offset += 50

        # Lines
        lines_text = self.small_font.render("LINES:", True, WHITE)
        self.screen.blit(lines_text, (sidebar_x + 20, y_offset))
        y_offset += 30
        lines_val = self.font.render(str(self.lines_cleared), True, WHITE)
        self.screen.blit(lines_val, (sidebar_x + 45, y_offset))
        y_offset += 50

        # Level
        level_text = self.small_font.render("LEVEL:", True, WHITE)
        self.screen.blit(level_text, (sidebar_x + 20, y_offset))
        y_offset += 30
        level_val = self.font.render(str(self.level), True, WHITE)
        self.screen.blit(level_val, (sidebar_x + 45, y_offset))
        y_offset += 70

        # Controls
        controls_text = self.small_font.render("CONTROLS:", True, WHITE)
        self.screen.blit(controls_text, (sidebar_x + 15, y_offset))
        y_offset += 30
        
        controls = [
            "← → : Move",
            "↑ : Rotate",
            "↓ : Soft Drop",
            "Space: Hard Drop",
            "P : Pause",
            "Esc : Quit"
        ]
        
        for control in controls:
            ctrl_text = self.small_font.render(control, True, GRAY)
            self.screen.blit(ctrl_text, (sidebar_x + 10, y_offset))
            y_offset += 25

    def draw_game_over(self):
        """Draw game over screen"""
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        overlay.fill(BLACK)
        overlay.set_alpha(180)
        self.screen.blit(overlay, (0, 0))
        
        game_over_text = self.font.render("GAME OVER", True, WHITE)
        score_text = self.small_font.render(f"Final Score: {self.score}", True, WHITE)
        restart_text = self.small_font.render("Press R to Restart or Esc to Quit", True, GRAY)
        
        self.screen.blit(game_over_text, 
                        (SCREEN_WIDTH // 2 - game_over_text.get_width() // 2, 
                         SCREEN_HEIGHT // 2 - 40))
        self.screen.blit(score_text,
                        (SCREEN_WIDTH // 2 - score_text.get_width() // 2,
                         SCREEN_HEIGHT // 2 + 10))
        self.screen.blit(restart_text,
                        (SCREEN_WIDTH // 2 - restart_text.get_width() // 2,
                         SCREEN_HEIGHT // 2 + 50))

    def draw_pause(self):
        """Draw pause overlay"""
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        overlay.fill(BLACK)
        overlay.set_alpha(180)
        self.screen.blit(overlay, (0, 0))
        
        pause_text = self.font.render("PAUSED", True, WHITE)
        resume_text = self.small_font.render("Press P to Resume", True, GRAY)
        
        self.screen.blit(pause_text,
                        (SCREEN_WIDTH // 2 - pause_text.get_width() // 2,
                         SCREEN_HEIGHT // 2))
        self.screen.blit(resume_text,
                        (SCREEN_WIDTH // 2 - resume_text.get_width() // 2,
                         SCREEN_HEIGHT // 2 + 40))

    def handle_input(self):
        """Handle player input"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                
                if self.game_over:
                    if event.key == pygame.K_r:
                        self.reset_game()
                    continue
                
                if event.key == pygame.K_p:
                    self.paused = not self.paused
                    continue
                
                if self.paused:
                    continue
                
                if event.key in (pygame.K_LEFT, pygame.K_a):
                    if self.valid_position(self.current_piece, offset_x=-1):
                        self.current_piece.x -= 1
                elif event.key in (pygame.K_RIGHT, pygame.K_d):
                    if self.valid_position(self.current_piece, offset_x=1):
                        self.current_piece.x += 1
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    if self.valid_position(self.current_piece, offset_y=1):
                        self.current_piece.y += 1
                        self.score += 1  # Soft drop bonus
                elif event.key == pygame.K_UP or event.key == pygame.K_w:
                    if self.valid_position(Tetromino()) or True:
                        old_shape = self.current_piece.shape.copy()
                        self.current_piece.rotate()
                        if not self.valid_position(self.current_piece):
                            # Wall kick - try moving left/right
                            for offset in [-1, 1, -2, 2]:
                                if self.valid_position(self.current_piece, offset_x=offset):
                                    self.current_piece.x += offset
                                    break
                elif event.key == pygame.K_SPACE:
                    # Hard drop
                    while self.valid_position(self.current_piece, offset_y=1):
                        self.current_piece.y += 1
                        self.score += 2
                    self.lock_piece()

        return True

    def update(self, dt):
        """Update game state"""
        if self.game_over or self.paused:
            return
        
        self.drop_time += dt
        
        if self.drop_time >= self.drop_interval:
            self.drop_time = 0
            
            if not self.valid_position(self.current_piece, offset_y=1):
                self.lock_piece()
            else:
                self.current_piece.y += 1

    def draw(self):
        """Draw everything"""
        self.screen.fill(BLACK)
        self.draw_grid()
        self.draw_board()
        self.draw_sidebar()
        
        if self.game_over:
            self.draw_game_over()
        elif self.paused:
            self.draw_pause()
        
        pygame.display.flip()

    def run(self):
        """Main game loop"""
        running = True
        
        while running:
            dt = self.clock.tick(60)  # Cap at 60 FPS
            
            if not self.handle_input():
                break
            
            self.update(dt)
            self.draw()
        
        pygame.quit()


def main():
    """Entry point"""
    print("=" * 50)
    print("TETRIS CLONE")
    print("=" * 50)
    print("\nControls:")
    print("  Arrow Keys: Move piece")
    print("  Up/W: Rotate piece")
    print("  Down/S: Soft drop")
    print("  Space: Hard drop")
    print("  P: Pause/Resume")
    print("  Esc: Quit game")
    print("\nStarting game... (Press Esc to quit anytime)")
    print("=" * 50 + "\n")
    
    game = TetrisGame()
    game.run()


if __name__ == "__main__":
    main()
