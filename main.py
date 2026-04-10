import sys
import json
import time
import math
import bisect
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
WIDTH, HEIGHT  = 1280, 720
FPS            = 60
GROUND_Y       = HEIGHT - 100   # suelo mas bajo proporcional a 720p
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

def build_background(width, height, ground_y):
    """
    Renderiza UNA SOLA VEZ el escenario del cielo (parallax lejano).
    En el loop principal se dibuja dos veces para efecto de scroll infinito continuo.
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

    # ── Estrellas Artísticas HD (componentes estrella 1-4) ────────────────────
    import random
    rng = random.Random(42)
    try:
        stars_assets = []
        for i in range(1, 5):
            path = f"components/estrella ({i}).png"
            stars_assets.append(pygame.image.load(path).convert_alpha())
        
        # Pesos: prioridad a estrella (2) y (3) -> indice 1 y 2
        # estrella(1): 10%, estrella(2): 35%, estrella(3): 45%, estrella(4): 10%
        star_pool = [0]*10 + [1]*35 + [2]*45 + [3]*10
        
        for _ in range(31):  # Reducido un 10% (35 -> 31) para menor saturación
            idx   = rng.choice(star_pool)
            scale = rng.uniform(0.4, 0.9) # Estrellas el doble de grandes o más
            raw_s = stars_assets[idx]
            sw    = int(raw_s.get_width() * scale)
            sh    = int(raw_s.get_height() * scale)
            star_inst = pygame.transform.scale(raw_s, (sw, sh))
            sx = rng.randint(0, width - sw)
            sy = rng.randint(0, ground_y - 120)
            surf.blit(star_inst, (sx, sy))
            
        # Puntos de "Polvo Estelar" (procedimental sutil para textura)
        for _ in range(72): # Reducido un 10% (80 -> 72)
            sx = rng.randint(0, width); sy = rng.randint(0, ground_y - 100)
            pygame.draw.circle(surf, (255, 255, 255, 150), (sx, sy), rng.randint(1, 2))
            
    except Exception as e:
        print(f"[Cielo] Error cargando estrellas: {e}")

    # ── Nubes Artísticas HD (componentes nube 1-3) ───────────────────────────
    try:
        clouds_assets = [
            pygame.image.load(f"components/nube{i}.png").convert_alpha() 
            for i in range(1, 4)
        ]
        # Posiciones dispersas (Reducido a 6 nubes para menos saturación)
        cloud_configs = [
            (50, 30, 0, 0.55), (320, 100, 1, 0.6), (620, 40, 2, 0.65), 
            (900, 110, 0, 0.5), (1120, 30, 1, 0.55), 
            (800, 190, 0, 0.4) # Eliminada una nube central baja
        ]
        for cx, cy, c_idx, c_scale in cloud_configs:
            raw_c = clouds_assets[c_idx]
            cw    = int(raw_c.get_width() * c_scale)
            ch    = int(raw_c.get_height() * c_scale)
            cloud_inst = pygame.transform.scale(raw_c, (cw, ch))
            surf.blit(cloud_inst, (cx, cy))
            
    except Exception as e:
        print(f"[Cielo] Error cargando nubes: {e}")

    return surf

def build_trees_layer(width, height, ground_y):
    """
    Capa de Parallax Media: Dibuja los árboles una sola vez en un Surface con transparencia.
    El ancho debe ser el de una pantalla (WIDTH), ya que lo repetiremos en el loop principal
    con un multiplicador de scroll parallax (ej: 0.7x).
    """
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    try:
        t1 = pygame.image.load("components/arboles1.png").convert_alpha()
        t2 = pygame.image.load("components/arboles2.png").convert_alpha()
        import random
        rng = random.Random(99) # semilla distinta al cielo
        
        # Generar un bioma estático de árboles que cubra 1 pantalla.
        for tx in range(30, width, 80):
            if rng.random() > 0.3: # 70% chance de arbol
                is_giant = (rng.random() > 0.85) # 15% chance gigante
                scale = rng.uniform(1.8, 2.1) if is_giant else rng.uniform(0.65, 1.4)
                t_type = 1 if rng.random() > 0.5 else 2
                raw = t1 if t_type == 1 else t2
                tw = int(120 * scale)
                th = int(160 * scale)
                tree_inst = pygame.transform.scale(raw, (tw, th))
                surf.blit(tree_inst, (tx + rng.randint(-20, 20), ground_y - th + 10))
    except Exception as e:
        print(f"[Cielo] Error cargando capa de árboles: {e}")
        
    return surf



# ==========================================
# 4. ENTIDADES SECUNDARIAS (Enemigos y Proyectiles)
# ==========================================
class Projectile(pygame.sprite.Sprite):
    def __init__(self, x, y, facing_right):
        super().__init__()
        self.image = pygame.Surface((24, 24), pygame.SRCALPHA)
        # Fallback gráfico: Estrella / Bola de energía amarilla
        pygame.draw.circle(self.image, (255, 255, 0), (12, 12), 12)
        pygame.draw.circle(self.image, (255, 200, 0), (12, 12), 8)
        self.rect = self.image.get_rect()
        self.rect.center = (x, y)
        self.velocity_x = 18 if facing_right else -18

    def update(self):
        self.rect.x += self.velocity_x

class Enemy(pygame.sprite.Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.image = pygame.Surface((40, 40))
        self.image.fill((255, 50, 50)) # Cubo rojo (Fallback)
        # Ojos amenazantes
        pygame.draw.rect(self.image, (0, 0, 0), (8, 8, 8, 8))
        pygame.draw.rect(self.image, (0, 0, 0), (24, 8, 8, 8))
        self.rect = self.image.get_rect()
        self.rect.centerx = x
        self.rect.bottom = y
        self.velocity_x = -3 # IA: Inicia patrullando hacia la izq
        self.velocity_y = 0
        self.gravity = 0.65
        
    def update(self, visible_platforms):
        # Movimiento horizontal Ping-Pong
        self.rect.x += self.velocity_x
        
        # Gravedad Simple
        self.velocity_y += self.gravity
        self.rect.y += int(self.velocity_y)
        
        on_ground = False
        current_platform = None
        
        if self.velocity_y >= 0:
            for plat in visible_platforms:
                if (self.rect.bottom >= plat.top and 
                    self.rect.bottom <= plat.top + 18 and 
                    self.rect.right > plat.left and 
                    self.rect.left < plat.right):
                    self.rect.bottom = plat.top
                    self.velocity_y = 0.0
                    on_ground = True
                    current_platform = plat
                    break
                    
        # Detección de caída (Edge Detection)
        if on_ground and current_platform:
            if self.rect.right > current_platform.right or self.rect.left < current_platform.left:
                self.velocity_x *= -1 # Invertir dirección de patrulla
                self.rect.x += self.velocity_x * 2 # Pequeño empujón seguro


# ==========================================
# 5. CLASE PLAYER — HD-2D con bob procedural
# ==========================================
class Player(pygame.sprite.Sprite):
    def __init__(self, ground_y, platforms):
        super().__init__()

        # ── Carga del sprite (con fallback a cápsula azul) ──────────────────
        try:
            raw = pygame.image.load("components/echo_idle.png").convert_alpha()
            # 130x140: Ahora con ancho extra para que se vea robusto y 'gordito'
            self.image_base = pygame.transform.scale(raw, (130, 140))
            print("[Player] Sprite components/echo_idle.png cargado y ajustado (130x140).")
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
        self.target_velocity_x = 0  # Velocidad deseada (para recuperar el ritmo tras knockback)
        self.speed       = 4
        self.gravity     = 0.65
        self.jump_power  = -21 # Incrementado un 50% para salto más alto
        self.is_jumping  = False
        # Bajamos al personaje 15px extra para que se hunda más en el diseño visual del suelo
        self.ground_y    = ground_y + 15

        # ── Jump Buffer + Coyote Time ────────────────────────────────────────
        self.jump_buffer   = 0
        self.coyote_frames = 0

        # ── Inventario y Daño ────────────────────────────────────────────────
        self.invulnerable_timer = 0
        self.facing_right = True
        self.projectiles = []

        # ── Ataque ────────────────────────────────────────────────────────────
        self.attack_timer  = 0
        self.is_attacking  = False

        # ── Bob de pasos ─────────────────────────────────────────────────────
        self.bounce_tick   = 0
        self._bob_offset   = 0     # Offset Y visual calculado en update()

    def take_damage(self):
        if self.invulnerable_timer == 0:
            self.invulnerable_timer = 60 # 1 segundo de i-frames
            self.velocity_x = -12 if self.facing_right else 12
            self.velocity_y = -6 # Pequeño salto por el daño
            return True
        return False

    def update(self, visible_platforms):
        # 1. Movimiento horizontal y Fricción/Decaimiento de Knockback
        if self.velocity_x > self.target_velocity_x:
            self.velocity_x -= 0.5
            if self.velocity_x < self.target_velocity_x:
                self.velocity_x = self.target_velocity_x
        elif self.velocity_x < self.target_velocity_x:
            self.velocity_x += 0.5
            if self.velocity_x > self.target_velocity_x:
                self.velocity_x = self.target_velocity_x

        self.rect.x += self.velocity_x
        
        # Clamp de mundo (No más Wrap)
        if self.rect.left < 0:
            self.rect.left = 0
            if self.velocity_x < 0:
                self.velocity_x = 0

        # Bloque temporal de límite derecho opcional
        # if self.rect.right > 31200: self.rect.right = 31200

        # 2. Gravedad
        self.velocity_y += self.gravity
        self.rect.y     += int(self.velocity_y)

        # 3. Colisión con suelo general (Fallback)
        on_ground = False
        if self.rect.bottom >= self.ground_y:
            self.rect.bottom = self.ground_y
            self.velocity_y  = 0.0
            self.is_jumping  = False
            on_ground        = True

        # 4. Colisión con plataformas flotantes sólidas y de suelo (Culling optimizado)
        if self.velocity_y >= 0:
            for plat in visible_platforms:
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

        # Update variables de acción y disparo
        if self.velocity_x > 0: self.facing_right = True
        elif self.velocity_x < 0: self.facing_right = False
        
        if self.invulnerable_timer > 0:
            self.invulnerable_timer -= 1
            
        for p in self.projectiles[:]:
            p.update()

        # 8. Imagen: ataque > flip según dirección
        if self.attack_timer > 0:
            self.attack_timer -= 1
            tinted = self.image_base.copy()
            tinted.fill((255, 50, 50, 0), special_flags=pygame.BLEND_RGB_ADD)
            self.image = tinted if self.facing_right else pygame.transform.flip(tinted, True, False)
        else:
            self.image        = self.image_base if self.facing_right else self.image_flip
            self.is_attacking = False

    def draw_with_bob(self, surface):
        """Blitea el sprite aplicando el offset de bob vertical y el parpadeo de invulnerabilidad."""
        if self.invulnerable_timer > 0 and (self.invulnerable_timer // 4) % 2 == 0:
            return # Parpadeo: no dibujar este frame
            
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

    def run(self):
        self.target_velocity_x = self.speed
        if abs(self.velocity_x) <= self.speed:
            self.velocity_x = self.speed

    def stop(self):
        self.target_velocity_x = 0
        if abs(self.velocity_x) <= self.speed:
            self.velocity_x = 0

    def attack(self):
        self.attack_timer = 20
        self.is_attacking = True
        proj_x = self.rect.right if self.facing_right else self.rect.left
        self.projectiles.append(Projectile(proj_x, self.rect.centery - 10, self.facing_right))


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

    # ── GENERACIÓN PROCEDIMENTAL DEL NIVEL (31,200 px) ────────────────────────
    import random
    rng = random.Random(101)
    
    # 1. Plataformas (Lista masiva pre-ordenada por X)
    platforms = []
    pos_x = 240
    while pos_x < 31200:
        pw = rng.randint(200, 600)
        py = GROUND_Y - rng.randint(150, 400)
        platforms.append(pygame.Rect(pos_x, py, pw, 48))
        pos_x += pw + rng.randint(150, 400) # gap aleatorio hasta la siguiente
        
    platforms_x = [p.x for p in platforms] # Lista K-V para bisect rápido

    # 2. Texturas Cacheadas (Suelo y Balcones)
    try:
        raw_piso = pygame.image.load("components/piso.png").convert_alpha()
        pw_piso, ph_piso = raw_piso.get_size()
        target_h = HEIGHT - (GROUND_Y - 40) + 10
        piso_stretched = pygame.transform.scale(raw_piso, (pw_piso, target_h))
    except:
        pw_piso, piso_stretched = 356, None

    try:
        raw_balcon = pygame.image.load("components/balcon.png").convert_alpha()
        bh_target = 76
        aspect_balcon = raw_balcon.get_width() / raw_balcon.get_height()
        bw_balcon = int(bh_target * aspect_balcon)
        balcon_scaled = pygame.transform.scale(raw_balcon, (bw_balcon, bh_target))
    except:
        bw_balcon, balcon_scaled = 100, None

    # 3. Chunks de Suelo Lineal
    ground_chunks = []
    gx = -60
    while gx < 31500:
        y_jitter = rng.randint(-8, 4)
        ground_chunks.append(pygame.Rect(gx, GROUND_Y - 40 + y_jitter, pw_piso, target_h))
        gx += (pw_piso - 10)
    ground_xs = [g.x for g in ground_chunks]

    # 4. Peligros, Enemigos y Meta (Fase 2)
    LEVEL_END_X = 31000
    victory = False

    hazards = []
    hx = 1200
    while hx < LEVEL_END_X - 1000:
        hw = rng.randint(60, 160)
        hazards.append(pygame.Rect(hx, GROUND_Y - 20, hw, 30))
        hx += rng.randint(800, 2500)
    hazards_x = [h.x for h in hazards]

    enemies = []
    ex = 1000
    while ex < LEVEL_END_X - 1000:
        enemies.append(Enemy(ex, GROUND_Y))
        ex += rng.randint(600, 1500)
        # 50% de probabilidad de generar otro sobre una plataforma aleatoria
        if rng.random() > 0.5:
            plat = rng.choice(platforms)
            if plat.x > 1000: # Evitar poner cerca del spawn
                enemies.append(Enemy(plat.centerx, plat.top))

    # ── PRE-RENDER CACHE (Parallax Layers) ────────────────────────────────────
    bg_sky     = build_background(WIDTH, HEIGHT, GROUND_Y)
    bg_trees   = build_trees_layer(WIDTH, HEIGHT, GROUND_Y)
    hud_bg     = build_hud_bg()

    # Variables de Cámara
    camera_x = 0

    # ── Sprites ───────────────────────────────────────────────────────────────
    player = Player(GROUND_Y, platforms) # Se inicializa sin plataformas atadas al mundo, luego update() define visibles

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

        # ── SISTEMA DE CÁMARA (SCROLLING LINEAL) ──────────────────────────────
        camera_x = max(0, player.rect.x - (WIDTH // 2 - 100))

        # ── FRUSTUM CULLING (Cálculo de Plataformas y Suelo Visibles) ─────────
        # Buscar el punto de inicio en el array ordenado
        idx_start_plat = bisect.bisect_left(platforms_x, camera_x - 1000)
        idx_end_plat   = bisect.bisect_right(platforms_x, camera_x + WIDTH)
        visible_platforms = platforms[max(0, idx_start_plat):idx_end_plat]

        idx_start_gnd = bisect.bisect_left(ground_xs, camera_x - pw_piso)
        idx_end_gnd   = bisect.bisect_right(ground_xs, camera_x + WIDTH)
        visible_grounds = ground_chunks[max(0, idx_start_gnd):idx_end_gnd]

        # Culling Hazards
        idx_start_haz = bisect.bisect_left(hazards_x, camera_x - 500)
        idx_end_haz   = bisect.bisect_right(hazards_x, camera_x + WIDTH)
        visible_hazards = hazards[max(0, idx_start_haz):idx_end_haz]
        
        # ── INTERACCIONES Y LÓGICA (Solo si no hemos ganado) ──────────────────
        if player.rect.centerx >= LEVEL_END_X and not victory:
            victory = True
            player.stop()

        if not victory:
            # Lógica de Enemigos y Proyectiles
            for e in enemies[:]:
                if camera_x - 200 < e.rect.x < camera_x + WIDTH + 200:
                    e.update(visible_platforms)
                    
                    # Colisión Jugador vs Enemigo
                    if e.rect.colliderect(player.rect):
                        if player.take_damage():
                            lives -= 1
                    
                    # Colisión Proyectil vs Enemigo
                    for p in player.projectiles[:]:
                        if p.rect.colliderect(e.rect):
                            if p in player.projectiles: player.projectiles.remove(p)
                            if e in enemies: enemies.remove(e)

            # Colisión con Hazards estáticos
            for haz in visible_hazards:
                if player.rect.colliderect(haz):
                    if player.take_damage():
                        lives -= 1

            # Mantenimiento de Proyectiles (Choques con terreno o fuera de cámara)
            for p in player.projectiles[:]:
                hit_plat = any(p.rect.colliderect(plat) for plat in visible_platforms)
                out_of_bounds = p.rect.x < camera_x - 300 or p.rect.x > camera_x + WIDTH + 300
                if hit_plat or out_of_bounds:
                    if p in player.projectiles: player.projectiles.remove(p)
                    
            # Update físico principal del jugador
            player.update(visible_platforms)
            if lives <= 0:
                pass # Aquí iría lógica de GameOver. Por ahora se quedará vivo a 0.

        # ── RENDER (PARALLAX + CULLING) ───────────────────────────────────────
        screen.fill(C_HUD_BG) # 1. Limpieza Absoluta de Pantalla
        
        # 2. Fondo de Cielo Infinito (0.1x Parallax continuo modular)
        bg_x = -(camera_x * 0.1) % WIDTH
        screen.blit(bg_sky, (bg_x, 0))
        screen.blit(bg_sky, (bg_x - WIDTH, 0))

        # 3. Bosque Infinito (Capa Media 0.7x Parallax continuo modular)
        trees_x = -(camera_x * 0.7) % WIDTH
        screen.blit(bg_trees, (trees_x, 0))
        screen.blit(bg_trees, (trees_x - WIDTH, 0))

        # 3. Suelo Visible (Espacio Físico Local)
        # Capa rosa trasera subyacente para huecos de rebote o parpadeo visual
        pygame.draw.rect(screen, (200, 80, 140), (0, GROUND_Y + 20, WIDTH, HEIGHT - GROUND_Y))
        
        for g_chunk in visible_grounds:
            if piso_stretched:
                screen.blit(piso_stretched, (g_chunk.x - camera_x, g_chunk.y))

        # 4. Plataformas Flotantes Visibles (Balcones Teselados)
        for plat in visible_platforms:
            if balcon_scaled:
                # Tiling del balcon visualmente para abarcar toda la plataforma
                tx = plat.x
                while tx < plat.right:
                    screen.blit(balcon_scaled, (tx - camera_x, plat.y - 12))
                    tx += (bw_balcon - 2)
            else:
                pygame.draw.rect(screen, C_PLATFORM, 
                                 (plat.x - camera_x, plat.y, plat.width, plat.height), 
                                 border_radius=4)
                                 
        # 5. Peligros / Hazards
        for haz in visible_hazards:
            # Dibujo de fluido tóxico simplificado
            pygame.draw.rect(screen, (50, 255, 50), (haz.x - camera_x, haz.y, haz.width, haz.height), border_radius=3)
            
        # 6. Enemigos
        for e in enemies:
            if camera_x - 200 < e.rect.x < camera_x + WIDTH + 200:
                screen.blit(e.image, (e.rect.x - camera_x, e.rect.y))
                
        # 7. Proyectiles
        for p in player.projectiles:
            screen.blit(p.image, (p.rect.x - camera_x, p.rect.y))
            
        # 8. Meta
        pygame.draw.rect(screen, (255, 215, 0), (LEVEL_END_X - camera_x, GROUND_Y - 300, 40, 300))

        # 5. Jugador (Relativo a cámara)
        # Modificamos el dibujo del offset vertical temporalmente interceptando su variable original de render:
        screen_x = player.rect.x - camera_x
        # player.draw_with_bob normally blits directly, we'll implement the custom manual blit relative to offset:
        # Puesto que draw_with_bob hace "surf.blit(self.image, (self.rect.x, self.rect.y + self._bob_offset))"
        # Tenemos que anular temporalmente rect.x para el render, sin afectar física:
        old_x = player.rect.x
        player.rect.x = screen_x
        player.draw_with_bob(screen)
        player.rect.x = old_x

        # Capa UI: Cartel Victoria
        if victory:
            # Box central
            vw, vh = 500, 100
            vx, vy = WIDTH // 2 - vw // 2, HEIGHT // 3
            pygame.draw.rect(screen, (30, 25, 40, 200), (vx, vy, vw, vh), border_radius=15)
            pygame.draw.rect(screen, (255, 215, 0), (vx, vy, vw, vh), 3, border_radius=15)
            # Text
            try:
                f_vic = pygame.font.SysFont("Consolas", 40, bold=True)
            except:
                f_vic = pygame.font.Font(None, 50)
            lbl_vic = f_vic.render("NIVEL COMPLETADO", True, (255, 215, 0))
            screen.blit(lbl_vic, (WIDTH // 2 - lbl_vic.get_width() // 2, vy + vh // 2 - lbl_vic.get_height() // 2))

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
