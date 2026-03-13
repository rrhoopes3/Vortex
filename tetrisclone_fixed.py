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
        [(0, 0), (1, 0), (2, 0), (3, 0)],
        [(0, 0), (0, 1), (0, 2), (0, 3)],
        [(0, 0), (-1, 0), (-2, 0), (-3, 0)],
        [(0, 0), (0, -1), (0, -2), (0, -3)]
    ],
    'O': [
        [(0, 0), (1, 0), (0, 1), (1, 1)],
        [(0, 0), (1, 0), (0, 1), (1, 1)],
        [(0, 0), (1, 0), (0, 1), (1, 1)],
        [(0, 0), (1, 0), (0, 1), (1, 1)]
    ],
    'T': [
        [(0, 0), (-1, 0), (1, 0), (0, -1)],
        [(0, 0), (0, -1), (0, 1), (1, 0)],
        [(0, 0), (-1, 0), (1, 0), (0, 1)],
        [(0, 0), (-1, 0), (0, -1), (0, 1)]
    ],
    'S': [
        [(0, 0), (1, 0), (0, 1), (1, 1)],
        [(0, 0), (0, 1), (1, 1), (1, 2)],
        [(0, 0), (-1, 0), (0, -1), (-1, -1)],
        [(0, 0), (0, -1), (-1, -1), (-1, -2)]
    ],
    'Z': [
        [(0, 0), (-1, 0), (0, 1), (-1, 1)],
        [(0, 0), (0, 1), (1, 1), (1, 2)],
        [(0, 0), (1, 0), (0, -1), (1, -1)],
        [(0, 0), (0, -1), (-1, -1), (-1, -2)]
    ],
    'J': [
        [(0, 0), (-1, 0), (1, 0), (1, -1)],
        [(0, 0), (0, -1), (0, 1), (1, 1)],
        [(0, 0), (-1, 0), (1, 0), (-1, 1)],
        [(0, 0), (0, -1), (0, 1), (-1, -1)]
    ],
    'L': [
        [(0, 0), (-1, 0), (1, 0), (-1, -1)],
        [(0, 0), (0, -1), (0, 1), (-1, 1)],
        [(0, 0), (-1, 0), (1, 0), (1, 1)],
        [(0, 0), (0, -1), (0, 1), (1, -1)]
    ]
}

class Tetromino:
    def __init__(self):
        self.type = random.choice(list(SHAPES.keys()))
        self.shape = SHAPES[self.type][0]
        self.color = COLORS[self.type]
        self.x = GRID_WIDTH // 2 - 2
        self.y = 0

    def rotate(self):
        """Rotate the piece clockwise"""
        # Get current rotation index (0-3)
        for i, shape in enumerate(SHAPES[self.type]):
            if shape == self.shape:
                next_rotation = (i + 1) % 4
                self.shape = SHAPES[self.type][next_rotation]
                break

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
            
            # Check boundaries
            if new_x < 0 or new_x >= GRID_WIDTH or new_y >= GRID_HEIGHT:
                return False
                
            # Check collision with placed pieces
            if new_y >= 0 and self.grid[new_y][new_x] is not None:
                return False
                
        return True

    def lock_piece(self):
        """Lock the current piece into the grid"""
        for x, y in self.current_piece.shape:
            grid_x = self.current_piece.x + x
            grid_y = self.current_piece.y + y
            
            if 0 <= grid_y < GRID_HEIGHT and 0 <= grid_x < GRID_WIDTH:
                self.grid[grid_y][grid_x] = self.current_piece.color
        
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
        
        # Remove cleared lines
        for line in lines_to_clear:
            del self.grid[line]
            self.grid.insert(0, [None] * GRID_WIDTH)
        
        # Update score and level
        if lines_to_clear:
            self.lines_cleared += len(lines_to_clear)
            self.score += [100, 300, 500, 800][min(len(lines_to_clear) - 1, 3)] * self.level
            
            # Level up every 10 lines
            self.level = self.lines_cleared // 10 + 1
            self.drop_interval = max(50, 500 - (self.level - 1) * 50)

    def draw_block(self, x, y, color):
        """Draw a single block"""
        rect = pygame.Rect(x * BLOCK_SIZE, y * BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE)
        pygame.draw.rect(self.screen, color, rect)
        # Add bevel effect
        pygame.draw.rect(self.screen, tuple(min(255, c + 40) for c in color), 
                        (rect.x, rect.y, rect.width - 1, rect.height - 1), 1)

    def draw_grid(self):
        """Draw the game grid background"""
        # Draw background
        pygame.draw.rect(self.screen, DARK_GRAY, (0, 0, GRID_WIDTH * BLOCK_SIZE, SCREEN_HEIGHT))
        
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
        """Draw the entire game board including locked pieces and current piece"""
        # Draw locked pieces
        for y in range(GRID_HEIGHT):
            for x in range(GRID_WIDTH):
                if self.grid[y][x] is not None:
                    self.draw_block(x, y, self.grid[y][x])
        
        # Draw ghost piece (where the current piece will land)
        if not self.game_over and not self.paused:
            ghost_y = 0
            while self.valid_position(self.current_piece, offset_y=ghost_y + 1):
                ghost_y += 1
            
            # Draw with semi-transparent color
            ghost_color = tuple(c // 2 for c in self.current_piece.color)
            for x, y in self.current_piece.shape:
                if y + ghost_y >= 0:  # Only draw visible parts
                    self.draw_block(self.current_piece.x + x, 
                                  self.current_piece.y + y + ghost_y, 
                                  ghost_color)

        # Draw current piece
        if not self.game_over and not self.paused:
            self.draw_piece(self.current_piece)

    def draw_sidebar(self):
        """Draw the sidebar with score and next piece"""
        sidebar_x = GRID_WIDTH * BLOCK_SIZE
        
        # Sidebar background
        pygame.draw.rect(self.screen, DARK_GRAY, (sidebar_x, 0, SIDEBAR_WIDTH, SCREEN_HEIGHT))
        
        y_offset = 20
        
        # Title
        title = self.font.render("TETRIS", True, WHITE)
        self.screen.blit(title, (sidebar_x + 50, y_offset))
        y_offset += 60

        # Score
        score_text = self.small_font.render(f"Score: {self.score}", True, WHITE)
        self.screen.blit(score_text, (sidebar_x + 20, y_offset))
        y_offset += 40
        
        # Lines cleared
        lines_text = self.small_font.render(f"Lines: {self.lines_cleared}", True, WHITE)
        self.screen.blit(lines_text, (sidebar_x + 20, y_offset))
        y_offset += 40
        
        # Level
        level_text = self.small_font.render(f"Level: {self.level}", True, WHITE)
        self.screen.blit(level_text, (sidebar_x + 20, y_offset))
        y_offset += 60

        # Next piece preview
        next_text = self.small_font.render("Next:", True, WHITE)
        self.screen.blit(next_text, (sidebar_x + 20, y_offset))
        y_offset += 30
        
        # Draw the next piece in a small grid
        if hasattr(self.next_piece, 'shape'):
            piece_x = sidebar_x + 60
            piece_y = y_offset
            
            for x, y in self.next_piece.shape:
                rect = pygame.Rect(piece_x + (x * BLOCK_SIZE), 
                                 piece_y + (y * BLOCK_SIZE), 
                                 BLOCK_SIZE, BLOCK_SIZE)
                pygame.draw.rect(self.screen, self.next_piece.color, rect)
                
                # Add bevel effect
                pygame.draw.rect(self.screen, tuple(min(255, c + 40) for c in self.next_piece.color),
                               (rect.x, rect.y, rect.width - 1, rect.height - 1), 1)

    def draw_game_over(self):
        """Draw game over screen"""
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        overlay.set_alpha(180)
        overlay.fill(BLACK)
        self.screen.blit(overlay, (0, 0))
        
        game_over_text = self.font.render("GAME OVER", True, WHITE)
        restart_text = self.small_font.render("Press R to Restart", True, WHITE)
        
        text_rect = game_over_text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 20))
        restart_rect = restart_text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 20))
        
        self.screen.blit(game_over_text, text_rect)
        self.screen.blit(restart_text, restart_rect)

    def draw_pause(self):
        """Draw pause screen"""
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        overlay.set_alpha(180)
        overlay.fill(BLACK)
        self.screen.blit(overlay, (0, 0))
        
        pause_text = self.font.render("PAUSED", True, WHITE)
        continue_text = self.small_font.render("Press P to Continue", True, WHITE)
        
        text_rect = pause_text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 20))
        continue_rect = continue_text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 20))
        
        self.screen.blit(pause_text, text_rect)
        self.screen.blit(continue_text, continue_rect)

    def handle_input(self):
        """Handle user input"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
                
            if event.type == pygame.KEYDOWN:
                if not self.game_over and not self.paused:
                    # Move pieces
                    if event.key == pygame.K_LEFT:
                        if self.valid_position(self.current_piece, offset_x=-1):
                            self.current_piece.x -= 1
                            
                    elif event.key == pygame.K_RIGHT:
                        if self.valid_position(self.current_piece, offset_x=1):
                            self.current_piece.x += 1
                            
                    elif event.key == pygame.K_DOWN:
                        if self.valid_position(self.current_piece, offset_y=1):
                            self.current_piece.y += 1
                            
                    elif event.key == pygame.K_UP:
                        # Rotate piece (simple rotation)
                        original_shape = self.current_piece.shape
                        self.current_piece.rotate()
                        # If rotation causes collision, revert it
                        if not self.valid_position(self.current_piece):
                            self.current_piece.shape = original_shape
                
                # Pause/unpause
                elif event.key == pygame.K_p:
                    self.paused = not self.paused
                    
                # Restart game
                elif event.key == pygame.K_r and self.game_over:
                    self.reset_game()
                    
        return True

    def update(self, dt):
        """Update game state"""
        if self.game_over or self.paused:
            return
            
        self.drop_time += dt
        
        # Move piece down at intervals based on level
        if self.drop_time >= self.drop_interval:
            self.drop_time = 0
            if not self.valid_position(self.current_piece, offset_y=1):
                self.lock_piece()
            else:
                self.current_piece.y += 1

    def draw(self):
        """Draw everything"""
        # Clear screen
        self.screen.fill(BLACK)
        
        # Draw game elements
        self.draw_grid()
        self.draw_board()
        self.draw_sidebar()
        
        # Draw overlays
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
            
            # Handle input
            running = self.handle_input()
            
            # Update game state
            self.update(dt)
            
            # Draw everything
            self.draw()

def main():
    """Main function"""
    try:
        game = TetrisGame()
        game.run()
    except Exception as e:
        print(f"Error: {e}")
        pygame.quit()
        sys.exit(1)

if __name__ == "__main__":
    main()