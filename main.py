import sys
import json
import time
import math
import multiprocessing
import numpy as np
import pygame
from voice_engine import VoiceController

# ==========================================
# 1. CARGA DE CONFIGURACIÓN
# ==========================================
def load_settings(path="settings.json"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error cargando settings: {e}")
        sys.exit(1)

settings = load_settings()
audio_cfg = settings.get("audio_settings", {})
ai_cfg    = settings.get("ai_model", {})

MIC_INDEX   = audio_cfg.get("microphone_index", 1)
SAMPLE_RATE = audio_cfg.get("sample_rate", 16000)
CHUNK_SIZE  = audio_cfg.get("chunk_size", 1024)
CHANNELS    = audio_cfg.get("channels", 1)
W_MODEL     = ai_cfg.get("whisper_model", "tiny")
COMMANDS    = settings.get("commands", {})

# ==========================================
# 2. CONSTANTES VISUALES
# ==========================================
WIDTH, HEIGHT  = 800, 450
FPS            = 60
GROUND_Y       = HEIGHT - 65   # Y de la superficie del suelo (top del rect)
DEBOUNCE_SECS  = 1.5

# Paleta "Star Candy"
C_SKY_TOP    = (60,  20, 100)
C_SKY_MID    = (130, 60, 180)
C_SKY_BOT    = (210, 110, 200)
C_PLATFORM   = (210, 140, 200)
C_PLAT_EDGE  = (160,  90, 220)
C_PLAT_BRICK = (180, 100, 160)
C_GROUND_TOP = (200, 130, 190)
C_GROUND_MID = (160, 100, 170)
C_STAR       = (255, 255, 210)
C_CLOUD      = (240, 215, 255)
C_DIAMOND    = (100, 230, 255)
C_COIN       = (255, 215,  60)
C_HUD_BG     = (20,  10,  40, 180)   # RGBA semi-transparente
C_HUD_TEXT   = (255, 255, 255)
C_CMD_ACTIVE = (100, 255, 140)
C_CMD_IDLE   = (180, 150, 220)
BLUE         = (80, 170, 255)


# ==========================================
# 3. PRE-RENDERIZADO DEL ESCENARIO ESTÁTICO
# ==========================================
def build_background(width, height, ground_y, platforms):
    """
    Genera el Surface maestro del escenario una sola vez.
    Incluye: gradiente de cielo, estrellas, nubes, plataformas y suelo con bordes.
    """
    surf = pygame.Surface((width, height))

    # --- Gradiente de cielo (3 bandas interpoladas) ---
    band_h = height // 3
    for y in range(height):
        if y < band_h:
            t = y / band_h
            r = int(C_SKY_TOP[0] + (C_SKY_MID[0] - C_SKY_TOP[0]) * t)
            g = int(C_SKY_TOP[1] + (C_SKY_MID[1] - C_SKY_TOP[1]) * t)
            b = int(C_SKY_TOP[2] + (C_SKY_MID[2] - C_SKY_TOP[2]) * t)
        elif y < band_h * 2:
            t = (y - band_h) / band_h
            r = int(C_SKY_MID[0] + (C_SKY_BOT[0] - C_SKY_MID[0]) * t)
            g = int(C_SKY_MID[1] + (C_SKY_BOT[1] - C_SKY_MID[1]) * t)
            b = int(C_SKY_MID[2] + (C_SKY_BOT[2] - C_SKY_MID[2]) * t)
        else:
            r, g, b = C_SKY_BOT
        pygame.draw.line(surf, (r, g, b), (0, y), (width, y))

    # --- Estrellas estáticas ---
    import random
    rng = random.Random(42)   # Seed fija para reproducibilidad
    for _ in range(80):
        sx = rng.randint(0, width)
        sy = rng.randint(0, ground_y - 80)
        sr = rng.randint(1, 3)
        pygame.draw.circle(surf, C_STAR, (sx, sy), sr)

    # --- Nubes (elipses superpuestas) ---
    cloud_defs = [
        (100, 70), (280, 50), (460, 90), (640, 60), (760, 80)
    ]
    for cx, cy in cloud_defs:
        for ox, oy, rw, rh in [
            (-30, 5, 40, 22), (0, 0, 50, 28), (30, 8, 35, 20)
        ]:
            pygame.draw.ellipse(surf, C_CLOUD, (cx + ox, cy + oy, rw * 2, rh * 2))

    # --- Decoración: hongos simples (roca + cabeza) ---
    mushroom_positions = [(680, ground_y - 30), (720, ground_y - 22)]
    for mx, my in mushroom_positions:
        pygame.draw.rect(surf, (200, 180, 210), (mx - 6, my, 12, 20))
        pygame.draw.ellipse(surf, (255, 80, 120), (mx - 16, my - 18, 32, 22))
        pygame.draw.circle(surf, (255, 255, 255), (mx - 6, my - 12), 3)
        pygame.draw.circle(surf, (255, 255, 255), (mx + 4, my - 8), 2)

    # --- Plataformas flotantes (pre-renderizadas) ---
    for plat_rect in platforms:
        _draw_platform(surf, plat_rect)

    # --- Suelo (ladrillo pixel art) ---
    ground_rect = pygame.Rect(0, ground_y, width, height - ground_y)
    pygame.draw.rect(surf, C_GROUND_TOP, ground_rect)
    # Borde superior iluminado
    pygame.draw.rect(surf, C_PLATFORM, (0, ground_y, width, 8))
    # Patrón de ladrillos
    brick_w, brick_h = 60, 18
    for row in range(3):
        offset = (brick_w // 2) if row % 2 else 0
        for col in range(-1, width // brick_w + 2):
            bx = col * brick_w + offset
            by = ground_y + 10 + row * brick_h
            pygame.draw.rect(surf, C_PLAT_BRICK, (bx + 2, by + 2, brick_w - 4, brick_h - 4))
            pygame.draw.rect(surf, C_PLAT_EDGE, (bx + 2, by + 2, brick_w - 4, brick_h - 4), 1)

    return surf


def _draw_platform(surf, rect):
    """Dibuja una plataforma flotante estilo ladrillo about sobre el surface dado."""
    # Cuerpo principal
    pygame.draw.rect(surf, C_PLATFORM, rect)
    # Borde superior claro
    pygame.draw.rect(surf, (230, 170, 230), (rect.x, rect.y, rect.width, 6))
    # Borde inferior oscuro
    pygame.draw.rect(surf, C_PLAT_EDGE, (rect.x, rect.bottom - 4, rect.width, 4))
    # Mini ladrillos internos
    brick_w = 36
    for i in range(rect.x, rect.x + rect.width, brick_w):
        pygame.draw.line(surf, C_PLAT_EDGE, (i, rect.y + 6), (i, rect.bottom - 4), 1)


# ==========================================
# 4. CLASE PLAYER
# ==========================================
class Player(pygame.sprite.Sprite):
    def __init__(self, ground_y, platforms):
        super().__init__()
        # Intentar cargar sprite de Echo con fallback a cuadrado azul
        try:
            self.image_base = pygame.image.load("echo_idle.png").convert_alpha()
            self.image_base = pygame.transform.scale(self.image_base, (52, 52))
        except Exception as e:
            print(f"[Error] No se pudo cargar echo_idle.png: {e}")
            self.image_base = pygame.Surface((40, 48), pygame.SRCALPHA)
            self.image_base.fill(BLUE)

        self.image       = self.image_base.copy()
        self.image_flip  = pygame.transform.flip(self.image_base, True, False)
        self.rect        = self.image.get_rect()
        self.rect.x      = 80
        self.rect.y      = ground_y - self.rect.height

        # Físicas
        self.velocity_y  = 0
        self.velocity_x  = 0
        self.speed       = 4
        self.gravity     = 0.65
        self.jump_power  = -14
        self.is_jumping  = False
        self.ground_y    = ground_y        # Y máxima del suelo
        self.platforms   = platforms       # Lista de pygame.Rect para colisión

        # Jump Buffer / Coyote Time
        self.jump_buffer    = 0
        self.coyote_frames  = 0            # Frames desde que dejó una plataforma

        # Ataque
        self.attack_timer   = 0
        self.is_attacking   = False

        # Animación de bounce
        self.bounce_tick    = 0

    def update(self):
        # 1. Movimiento Horizontal + Screen Wrap
        self.rect.x += self.velocity_x
        if self.rect.right < 0:  self.rect.left  = WIDTH
        if self.rect.left > WIDTH: self.rect.right = 0

        # 2. Gravedad
        self.velocity_y += self.gravity
        self.rect.y     += int(self.velocity_y)

        # 3. Colisión con suelo
        on_ground = False
        if self.rect.bottom >= self.ground_y:
            self.rect.bottom = self.ground_y
            self.velocity_y  = 0
            self.is_jumping  = False
            on_ground        = True

        # 4. Colisión con plataformas flotantes (solo por arriba)
        if self.velocity_y >= 0:
            for plat in self.platforms:
                if (self.rect.bottom >= plat.top
                        and self.rect.bottom <= plat.top + 16
                        and self.rect.right  > plat.left + 4
                        and self.rect.left   < plat.right - 4):
                    self.rect.bottom = plat.top
                    self.velocity_y  = 0
                    self.is_jumping  = False
                    on_ground        = True
                    break

        # 5. Coyote Time (6 frames tras perder suelo)
        if on_ground:
            self.coyote_frames = 6
        elif self.coyote_frames > 0:
            self.coyote_frames -= 1

        # 6. Jump Buffer ejecutado al aterrizar
        if on_ground and self.jump_buffer > 0:
            self.velocity_y   = self.jump_power
            self.is_jumping   = True
            self.jump_buffer  = 0

        if self.jump_buffer > 0:
            self.jump_buffer -= 1

        # 7. Animación: bounce horizontal y flip de sprite
        if self.velocity_x != 0:
            self.bounce_tick   += 1
            bob                 = int(math.sin(self.bounce_tick * 0.25) * 2)
            visual_rect         = self.image.get_rect(topleft=self.rect.topleft)
            visual_rect.y      += bob
        else:
            self.bounce_tick = 0

        # 8. Ataque visual
        if self.attack_timer > 0:
            self.attack_timer -= 1
            atk = self.image_base.copy()
            atk.fill((255, 50, 50), special_flags=pygame.BLEND_RGB_MULT)
            self.image = atk
        else:
            # Flip según dirección
            if self.velocity_x < 0:
                self.image = self.image_flip
            else:
                self.image = self.image_base
            self.is_attacking = False

    # --- Acciones de Voz ---
    def queue_jump(self):
        if self.coyote_frames > 0 and not self.is_jumping:
            self.velocity_y    = self.jump_power
            self.is_jumping    = True
            self.coyote_frames = 0
        else:
            self.jump_buffer = 30

    def run(self):
        self.velocity_x = self.speed

    def stop(self):
        self.velocity_x = 0

    def attack(self):
        self.attack_timer = 20
        self.is_attacking = True


# ==========================================
# 5. HUD FUNCTIONS (pre-renderiza piezas fijas)
# ==========================================
def build_hud_bg(font_sm):
    """Crea el panel de fondo del HUD una sola vez."""
    surf = pygame.Surface((320, 64), pygame.SRCALPHA)
    surf.fill((20, 10, 40, 180))
    pygame.draw.rect(surf, (160, 100, 220), surf.get_rect(), 2, border_radius=10)
    label = font_sm.render("🎤  VOICE-QUEST", True, (200, 160, 255))
    surf.blit(label, (12, 6))
    return surf


def draw_hud(screen, hud_bg, font_sm, font_md, last_command, cmd_color,
             last_cmd_time, debounce_secs):
    """Blit del panel + texto dinámico + barra de cooldown en cada frame."""
    screen.blit(hud_bg, (10, 10))

    # Texto del ultimo comando
    cmd_surf = font_md.render(last_command, True, cmd_color)
    screen.blit(cmd_surf, (22, 34))

    # Barra de cooldown
    elapsed  = time.time() - last_cmd_time
    progress = min(elapsed / debounce_secs, 1.0)
    bar_w    = 296
    bar_h    = 6
    bar_x, bar_y = 14, 72
    pygame.draw.rect(screen, (60, 30, 80),   (bar_x, bar_y, bar_w, bar_h), border_radius=3)
    fill_w = int(bar_w * progress)
    color  = C_CMD_ACTIVE if progress >= 1.0 else (200, 100, 240)
    if fill_w > 0:
        pygame.draw.rect(screen, color, (bar_x, bar_y, fill_w, bar_h), border_radius=3)


# ==========================================
# 6. MAIN
# ==========================================
def set_game_affinity():
    import psutil, os
    try:
        psutil.Process(os.getpid()).nice(psutil.HIGH_PRIORITY_CLASS)
    except:
        pass


def main():
    set_game_affinity()
    print("[Pygame] Inicializando motor gráfico Star Candy Edition...")
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Voice-Quest  ★  Star Candy Edition")
    clock  = pygame.time.Clock()

    # --- Fuentes ---
    pygame.font.init()
    try:
        font_sm = pygame.font.SysFont("Consolas", 14, bold=True)
        font_md = pygame.font.SysFont("Consolas", 20, bold=True)
    except:
        font_sm = pygame.font.SysFont("Arial", 14)
        font_md = pygame.font.SysFont("Arial", 20)

    # --- Plataformas flotantes (Rects de colisión + renderizado) ---
    platforms = [
        pygame.Rect(160, GROUND_Y - 130, 140, 22),
        pygame.Rect(400, GROUND_Y - 185, 160, 22),
        pygame.Rect(600, GROUND_Y - 115, 140, 22),
    ]

    # --- PRE-RENDER ÚNICO del escenario estático ---
    bg_surface = build_background(WIDTH, HEIGHT, GROUND_Y, platforms)
    hud_bg     = build_hud_bg(font_sm)

    # --- Sprites ---
    player      = Player(GROUND_Y, platforms)
    all_sprites = pygame.sprite.Group(player)

    # --- Cola de voz ---
    cmd_queue     = multiprocessing.Queue(maxsize=1)
    voice_process = VoiceController(cmd_queue, settings)
    voice_process.start()

    # --- Estado HUD ---
    last_command  = "ESPERANDO VOZ..."
    cmd_color     = C_CMD_IDLE
    last_cmd_time = 0.0

    # --- MAIN ENGINE LOOP ---
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

        # --- Consumo de cola: UN comando por frame ---
        try:
            raw_action = cmd_queue.get_nowait().lower().strip(".,!? ")
            tokens = set(raw_action.split())
            last_command  = f"→  {raw_action.upper()}"
            cmd_color     = C_CMD_ACTIVE
            last_cmd_time = time.time()

            # Prioridad: STOP > ATTACK > RUN > JUMP
            # Sincronizado con confusion_matrix de voice_engine.py
            STOP_SET   = {"stop","para","pare","paro","parar","frena","frenar",
                          "alto","detente","quieto","espera","basta","suficiente",
                          "halt","bada","badaa","bad","bara"}
            ATTACK_SET = {"attack","ataca","ataque","atacar","ataco",
                          "golpea","golpe","golpear","pega","pegar",
                          "dispara","disparar","adaca"}
            RUN_SET    = {"run","corre","corra","correr","corres","corriendo",
                          "avanza","avanzar","mueve","moverse","anda","andar","vete"}
            JUMP_SET   = {"jump","salta","salte","saltar","salto","saltas",
                          "brinca","brincar","sube","subir","arriba",
                          "sawta","salda","sadda","sanda"}

            if   tokens & STOP_SET:
                player.stop()
            elif tokens & ATTACK_SET:
                player.attack()
            elif tokens & RUN_SET:
                player.run()
            elif tokens & JUMP_SET:
                player.queue_jump()
        except multiprocessing.queues.Empty:
            pass
        except Exception as e:
            print(f"[Engine] Error en cola: {e}")

        # --- Lógica ---
        all_sprites.update()

        # --- Render ---
        # 1. Un solo blit del escenario pre-renderizado (O(1) para el escenario completo)
        screen.blit(bg_surface, (0, 0))

        # 2. Sprites dinámicos (solo Echo)
        all_sprites.draw(screen)

        # 3. HUD dinámico
        draw_hud(screen, hud_bg, font_sm, font_md,
                 last_command, cmd_color, last_cmd_time, DEBOUNCE_SECS)

        pygame.display.flip()
        clock.tick(FPS)

    print("[Pygame] Apagando el juego...")
    voice_process.terminate()
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
