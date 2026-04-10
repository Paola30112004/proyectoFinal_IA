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

settings   = load_settings()
audio_cfg  = settings.get("audio_settings", {})
ai_cfg     = settings.get("ai_model", {})
W_MODEL    = ai_cfg.get("whisper_model", "tiny")
COMMANDS   = settings.get("commands", {})

# ==========================================
# 2. CONSTANTES VISUALES — "STAR CANDY ADVENTURES"
# ==========================================
WIDTH, HEIGHT  = 800, 450
FPS            = 60
GROUND_Y       = HEIGHT - 65
DEBOUNCE_SECS  = 1.5

# Paleta Espacial-Dulce (tonos pastel cósmicos)
C_SKY_TOP    = ( 18,   8,  55)   # Azul noche profundo
C_SKY_MID    = ( 65,  20, 120)   # Púrpura galáctica
C_SKY_BOT    = (150,  60, 190)   # Magenta crepuscular
C_NEBULA_A   = (255, 100, 160, 30)  # Rosa nebulosa (con alpha)
C_NEBULA_B   = ( 80, 160, 255, 20)  # Azul nebulosa (con alpha)
C_PLATFORM   = ( 60, 210, 230)   # Cian neón
C_PLAT_LIGHT = (160, 255, 255)   # Cian claro para borde superior
C_PLAT_DARK  = ( 20, 130, 160)   # Cian oscuro para sombra
C_PLAT_BRICK = ( 40, 180, 210)   # Ladrillo cian medio
C_GROUND_TOP = (255, 120, 180)   # Rosa chicle — superficie suelo
C_GROUND_MID = (200,  70, 140)   # Rosa oscuro — cuerpo suelo
C_STAR       = (255, 255, 210)   # Estrella blanca-cálida
C_STAR_BLUE  = (160, 220, 255)   # Estrella fría
C_CLOUD      = (255, 210, 240, 160)  # Nube pastel rosada
C_DIAMOND    = (100, 240, 255)   # Cian brillante
C_HUD_BG     = ( 10,   5,  35, 200)  # Negro cósmico semi-transparente
C_HUD_BORDER = (140,  80, 255)   # Borde púrpura neón
C_HUD_LABEL  = (200, 160, 255)   # Texto label tenue
C_CMD_ACTIVE = ( 80, 255, 160)   # Verde neón: comando activo
C_CMD_IDLE   = (120, 100, 180)   # Púrpura tenue: esperando
C_LIFE_ON    = (255, 100, 120)   # Vida activa (rosa)
C_LIFE_OFF   = ( 80,  40,  80)   # Vida perdida (oscuro)
C_FALLBACK   = ( 80, 170, 255)   # Color fallback del sprite

# Sets de comandos (sincronizados con voice_engine.py confusion_matrix)
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


# ==========================================
# 3. SURFACE CACHING — Escenario Estático
# ==========================================
def _lerp_color(c1, c2, t):
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )

def _draw_platform(surf, rect):
    """Dibuja plataforma estilo ciberpunk-cian sobre un Surface."""
    # Cuerpo principal
    pygame.draw.rect(surf, C_PLATFORM, rect, border_radius=4)
    # Borde superior iluminado (luz cenital)
    pygame.draw.rect(surf, C_PLAT_LIGHT,
                     (rect.x, rect.y, rect.width, 5), border_radius=4)
    # Sombra inferior
    pygame.draw.rect(surf, C_PLAT_DARK,
                     (rect.x, rect.bottom - 4, rect.width, 4), border_radius=2)
    # Separadores de ladrillo verticales
    brick_w = 38
    for bx in range(rect.x + brick_w, rect.right, brick_w):
        pygame.draw.line(surf, C_PLAT_DARK,
                         (bx, rect.y + 5), (bx, rect.bottom - 4), 1)
    # Destello especular pequeño (fake 3D)
    pygame.draw.ellipse(surf, (240, 255, 255),
                        (rect.x + 8, rect.y + 1, 28, 3))


def build_background(width, height, ground_y, platforms):
    """
    Renderiza UNA SOLA VEZ el escenario completo.
    En el loop principal solo se hace screen.blit(bg_surface, (0,0)).
    """
    surf = pygame.Surface((width, height))

    # ── Gradiente de cielo en 3 tramos ──────────────────────────────────────
    band_h = height // 3
    for y in range(height):
        if y < band_h:
            c = _lerp_color(C_SKY_TOP, C_SKY_MID, y / band_h)
        elif y < band_h * 2:
            c = _lerp_color(C_SKY_MID, C_SKY_BOT, (y - band_h) / band_h)
        else:
            c = C_SKY_BOT
        pygame.draw.line(surf, c, (0, y), (width, y))

    # ── Nebulosas difusas (Surfaces con alpha bliteadas) ─────────────────────
    neb = pygame.Surface((260, 120), pygame.SRCALPHA)
    pygame.draw.ellipse(neb, C_NEBULA_A, neb.get_rect())
    surf.blit(neb, (80, 30))
    neb2 = pygame.Surface((200, 90), pygame.SRCALPHA)
    pygame.draw.ellipse(neb2, C_NEBULA_B, neb2.get_rect())
    surf.blit(neb2, (480, 60))

    # ── Estrellas de dos tonos, tamaños variados ─────────────────────────────
    import random
    rng = random.Random(42)
    for _ in range(110):
        sx  = rng.randint(0, width)
        sy  = rng.randint(0, ground_y - 80)
        sr  = rng.randint(1, 3)
        col = C_STAR if rng.random() > 0.35 else C_STAR_BLUE
        pygame.draw.circle(surf, col, (sx, sy), sr)
    # Estrellas grandes con cruz de destello
    for _ in range(8):
        sx = rng.randint(20, width - 20)
        sy = rng.randint(10, ground_y - 80)
        br = rng.randint(2, 4)
        pygame.draw.circle(surf, C_STAR, (sx, sy), br)
        pygame.draw.line(surf, C_STAR, (sx - br*2, sy), (sx + br*2, sy), 1)
        pygame.draw.line(surf, C_STAR, (sx, sy - br*2), (sx, sy + br*2), 1)

    # ── Nubes pastel con alpha ───────────────────────────────────────────────
    cloud_defs = [(90, 65), (270, 48), (450, 85), (635, 55), (755, 75)]
    for cx, cy in cloud_defs:
        for ox, oy, rw, rh in [(-32, 6, 42, 24), (0, 0, 54, 30), (32, 9, 38, 22)]:
            cloud_s = pygame.Surface((rw*2, rh*2), pygame.SRCALPHA)
            pygame.draw.ellipse(cloud_s, C_CLOUD, cloud_s.get_rect())
            surf.blit(cloud_s, (cx + ox, cy + oy))

    # ── Hongos decorativos ───────────────────────────────────────────────────
    for mx, my in [(675, ground_y - 34), (715, ground_y - 24)]:
        pygame.draw.rect(surf, (200, 180, 220), (mx - 6, my, 12, 22))
        pygame.draw.ellipse(surf, (255, 80, 140), (mx - 17, my - 20, 34, 24))
        pygame.draw.circle(surf, (255, 255, 255), (mx - 6, my - 13), 3)
        pygame.draw.circle(surf, (255, 255, 255), (mx + 5, my - 8), 2)

    # ── Plataformas flotantes ciberpunk-cian ─────────────────────────────────
    for plat_rect in platforms:
        _draw_platform(surf, plat_rect)

    # ── Suelo: rosa chicle con ladrillos ─────────────────────────────────────
    ground_rect = pygame.Rect(0, ground_y, width, height - ground_y)
    pygame.draw.rect(surf, C_GROUND_MID, ground_rect)
    # Franja superior rosa brillante
    pygame.draw.rect(surf, C_GROUND_TOP, (0, ground_y, width, 10))
    # Línea de brillo blanca ultra-fina
    pygame.draw.line(surf, (255, 200, 230), (0, ground_y), (width, ground_y), 1)
    # Ladrillos desfasados
    bw, bh = 64, 20
    for row in range(3):
        off = (bw // 2) if row % 2 else 0
        for col in range(-1, width // bw + 2):
            bx = col * bw + off
            by = ground_y + 12 + row * bh
            pygame.draw.rect(surf, (220, 90, 150),  (bx+2, by+2, bw-4, bh-4))
            pygame.draw.rect(surf, (240, 130, 180), (bx+2, by+2, bw-4, 3))   # borde claro
            pygame.draw.rect(surf, (160, 50, 110),  (bx+2, by+2, bw-4, bh-4), 1)  # borde oscuro

    return surf


# ==========================================
# 4. CLASE PLAYER — HD-2D con bob procedural
# ==========================================
class Player(pygame.sprite.Sprite):
    def __init__(self, ground_y, platforms):
        super().__init__()

        # ── Carga del sprite (con fallback a cápsula azul) ──────────────────
        try:
            raw = pygame.image.load("echo_idle.png").convert_alpha()
            self.image_base = pygame.transform.scale(raw, (56, 56))
            print("[Player] Sprite echo_idle.png cargado correctamente.")
        except Exception as e:
            print(f"[Player] Fallback: {e}")
            self.image_base = pygame.Surface((40, 52), pygame.SRCALPHA)
            # Cápsula azul degradada como fallback premium
            for row in range(52):
                t   = row / 52
                col = _lerp_color(C_FALLBACK, (30, 80, 160), t)
                pygame.draw.line(self.image_base, col, (4, row), (36, row))
            pygame.draw.rect(self.image_base, (140, 210, 255), (4, 0, 32, 52), 2, border_radius=8)

        self.image_flip = pygame.transform.flip(self.image_base, True, False)
        self.image      = self.image_base.copy()
        self.rect       = self.image.get_rect()
        self.rect.x     = 80
        self.rect.y     = ground_y - self.rect.height

        # ── Físicas ──────────────────────────────────────────────────────────
        self.velocity_y  = 0.0
        self.velocity_x  = 0
        self.speed       = 4
        self.gravity     = 0.65
        self.jump_power  = -14
        self.is_jumping  = False
        self.ground_y    = ground_y
        self.platforms   = platforms

        # ── Jump Buffer + Coyote Time ────────────────────────────────────────
        self.jump_buffer   = 0
        self.coyote_frames = 0

        # ── Ataque ────────────────────────────────────────────────────────────
        self.attack_timer  = 0
        self.is_attacking  = False

        # ── Bob de pasos ─────────────────────────────────────────────────────
        self.bounce_tick   = 0
        self._bob_offset   = 0     # Offset Y visual calculado en update()

    def update(self):
        # 1. Movimiento horizontal + wrap
        self.rect.x += self.velocity_x
        if self.rect.right < 0:   self.rect.left  = WIDTH
        if self.rect.left  > WIDTH: self.rect.right = 0

        # 2. Gravedad
        self.velocity_y += self.gravity
        self.rect.y     += int(self.velocity_y)

        # 3. Colisión con suelo
        on_ground = False
        if self.rect.bottom >= self.ground_y:
            self.rect.bottom = self.ground_y
            self.velocity_y  = 0.0
            self.is_jumping  = False
            on_ground        = True

        # 4. Colisión con plataformas flotantes (solo desde arriba)
        if self.velocity_y >= 0:
            for plat in self.platforms:
                if (self.rect.bottom >= plat.top
                        and self.rect.bottom <= plat.top + 18
                        and self.rect.right  > plat.left + 4
                        and self.rect.left   < plat.right - 4):
                    self.rect.bottom = plat.top
                    self.velocity_y  = 0.0
                    self.is_jumping  = False
                    on_ground        = True
                    break

        # 5. Coyote Time
        if on_ground:
            self.coyote_frames = 6
        elif self.coyote_frames > 0:
            self.coyote_frames -= 1

        # 6. Jump Buffer al aterrizar
        if on_ground and self.jump_buffer > 0:
            self.velocity_y  = self.jump_power
            self.is_jumping  = True
            self.jump_buffer = 0
        if self.jump_buffer > 0:
            self.jump_buffer -= 1

        # 7. Bob procedural de pasos (solo en suelo y corriendo)
        if self.velocity_x != 0 and on_ground:
            self.bounce_tick += 1
            self._bob_offset  = int(math.sin(self.bounce_tick * 0.30) * 2)
        else:
            if self.velocity_x == 0:
                self.bounce_tick = 0
            self._bob_offset = 0

        # 8. Imagen: ataque > flip según dirección
        if self.attack_timer > 0:
            self.attack_timer -= 1
            tinted = self.image_base.copy()
            tinted.fill((255, 50, 50, 0), special_flags=pygame.BLEND_RGB_ADD)
            self.image = tinted
        else:
            self.image        = self.image_flip if self.velocity_x < 0 else self.image_base
            self.is_attacking = False

    def draw_with_bob(self, surface):
        """Blitea el sprite aplicando el offset de bob vertical."""
        draw_pos = (self.rect.x, self.rect.y + self._bob_offset)
        surface.blit(self.image, draw_pos)

    # ── Acciones de voz ──────────────────────────────────────────────────────
    def queue_jump(self):
        if self.coyote_frames > 0 and not self.is_jumping:
            self.velocity_y    = self.jump_power
            self.is_jumping    = True
            self.coyote_frames = 0
        else:
            self.jump_buffer = 30

    def run(self):    self.velocity_x = self.speed
    def stop(self):   self.velocity_x = 0
    def attack(self):
        self.attack_timer = 20
        self.is_attacking = True


# ==========================================
# 5. HUD — Panel Neón semi-transparente
# ==========================================
MAX_LIVES = 5

def build_hud_bg():
    """Panel base del HUD generado una sola vez (200px de alto para íconos + barra)."""
    surf = pygame.Surface((340, 82), pygame.SRCALPHA)
    # Fondo oscuro cósmico
    pygame.draw.rect(surf, C_HUD_BG, surf.get_rect(), border_radius=12)
    # Borde doble: interno claro, externo púrpura
    pygame.draw.rect(surf, C_HUD_BORDER, surf.get_rect(), 2, border_radius=12)
    pygame.draw.rect(surf, (80, 40, 140), surf.get_rect().inflate(-4, -4), 1, border_radius=10)
    # Label "VOICE-QUEST" grabado
    try:
        f = pygame.font.SysFont("Consolas", 11, bold=True)
    except:
        f = pygame.font.Font(None, 14)
    lbl = f.render("★  VOICE-QUEST  ★", True, C_HUD_LABEL)
    surf.blit(lbl, (surf.get_width()//2 - lbl.get_width()//2, 5))
    return surf


def draw_hud(screen, hud_bg, font_sm, font_md, last_command, cmd_color,
             last_cmd_time, debounce_secs, lives):
    HX, HY = 10, 10

    # 1. Panel de fondo cacheado
    screen.blit(hud_bg, (HX, HY))

    # 2. Círculos de vidas (corazones simulados)
    for i in range(MAX_LIVES):
        col = C_LIFE_ON if i < lives else C_LIFE_OFF
        cx  = HX + 16 + i * 24
        cy  = HY + 22
        pygame.draw.circle(screen, col, (cx, cy), 8)
        # Destello superior simulando volumen 3D
        pygame.draw.circle(screen, (255, 200, 210) if i < lives else (100, 60, 100),
                           (cx - 2, cy - 3), 3)

    # 3. Texto del comando reconocido (con sombra para legibilidad)
    cmd_text = last_command[:26]   # Truncar si es muy largo
    shadow   = font_md.render(cmd_text, True, (0, 0, 0))
    cmd_surf = font_md.render(cmd_text, True, cmd_color)
    screen.blit(shadow,   (HX + 15, HY + 41))
    screen.blit(cmd_surf, (HX + 14, HY + 40))

    # 4. Barra de cooldown tipo "carga de habilidad"
    elapsed  = time.time() - last_cmd_time
    progress = min(elapsed / debounce_secs, 1.0)
    bx, by   = HX + 14, HY + 68
    bw, bh   = 312, 7
    # Fondo de la barra
    pygame.draw.rect(screen, (40, 20, 70), (bx, by, bw, bh), border_radius=4)
    # Relleno de progreso con color dinámico
    fill_w = int(bw * progress)
    if fill_w > 0:
        bar_color = C_CMD_ACTIVE if progress >= 1.0 else (180, 80, 240)
        pygame.draw.rect(screen, bar_color, (bx, by, fill_w, bh), border_radius=4)
    # Micro-borde de la barra
    pygame.draw.rect(screen, C_HUD_BORDER, (bx, by, bw, bh), 1, border_radius=4)


# ==========================================
# 6. HELPERS DE SISTEMA
# ==========================================
def set_game_affinity():
    import psutil, os
    try:
        psutil.Process(os.getpid()).nice(psutil.HIGH_PRIORITY_CLASS)
    except:
        pass


# ==========================================
# 7. MAIN LOOP
# ==========================================
def main():
    set_game_affinity()
    print("[Pygame] Inicializando motor gráfico Star Candy Adventures...")
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Voice-Quest  ★  Star Candy Adventures")
    clock  = pygame.time.Clock()

    # ── Fuentes ──────────────────────────────────────────────────────────────
    pygame.font.init()
    try:
        font_sm = pygame.font.SysFont("Consolas", 13, bold=True)
        font_md = pygame.font.SysFont("Consolas", 19, bold=True)
    except:
        font_sm = pygame.font.Font(None, 16)
        font_md = pygame.font.Font(None, 22)

    # ── Plataformas (Rects de física + visual) ────────────────────────────────
    platforms = [
        pygame.Rect(155, GROUND_Y - 130, 145, 20),
        pygame.Rect(395, GROUND_Y - 190, 165, 20),
        pygame.Rect(595, GROUND_Y - 118, 145, 20),
    ]

    # ── PRE-RENDER ÚNICO (Surface Caching) ────────────────────────────────────
    bg_surface = build_background(WIDTH, HEIGHT, GROUND_Y, platforms)
    hud_bg     = build_hud_bg()

    # ── Sprites ───────────────────────────────────────────────────────────────
    player = Player(GROUND_Y, platforms)

    # ── Cola y proceso de voz ─────────────────────────────────────────────────
    cmd_queue     = multiprocessing.Queue(maxsize=1)
    voice_process = VoiceController(cmd_queue, settings)
    voice_process.start()

    # ── Estado HUD ────────────────────────────────────────────────────────────
    last_command  = "ESPERANDO VOZ..."
    cmd_color     = C_CMD_IDLE
    last_cmd_time = 0.0
    lives         = MAX_LIVES

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN ENGINE LOOP
    # ─────────────────────────────────────────────────────────────────────────
    running = True
    while running:
        # ── Eventos ──────────────────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

        # ── Consumo de cola: UN comando por frame ─────────────────────────────
        try:
            raw_action    = cmd_queue.get_nowait().lower().strip(".,!? ¡¿")
            tokens        = set(raw_action.split())
            last_command  = f"  {raw_action.upper()}"
            cmd_color     = C_CMD_ACTIVE
            last_cmd_time = time.time()

            # Prioridad: STOP > ATTACK > RUN > JUMP
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

        # ── Fade del color del comando tras el debounce ───────────────────────
        if time.time() - last_cmd_time > DEBOUNCE_SECS:
            cmd_color = C_CMD_IDLE

        # ── Lógica del jugador ────────────────────────────────────────────────
        player.update()

        # ── RENDER ────────────────────────────────────────────────────────────
        # O(1): un solo blit del Surface maestro pre-renderizado
        screen.blit(bg_surface, (0, 0))

        # Jugador con bob vertical procedural
        player.draw_with_bob(screen)

        # HUD dinámico (solo texto + barra cambian cada frame)
        draw_hud(screen, hud_bg, font_sm, font_md,
                 last_command, cmd_color, last_cmd_time, DEBOUNCE_SECS, lives)

        pygame.display.flip()
        clock.tick(FPS)

    print("[Pygame] Apagando el juego...")
    voice_process.terminate()
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
