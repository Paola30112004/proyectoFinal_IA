import sys
import json
import time
import math
import bisect
import multiprocessing
import numpy as np
import pygame
import random
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
# PRE-CÁLCULO: POOL DE TEXTURAS DE BALCONES
# ==========================================
def load_platform_textures(target_height):
    """Carga y escala las texturas proporcionalmente en RAM una sola vez."""
    textures = []
    for i in range(1, 7):
        try:
            raw_img = pygame.image.load(f"components/Elementos_Espaciales1/balcon ({i}).png").convert_alpha()
            aspect = raw_img.get_width() / raw_img.get_height()
            scaled_img = pygame.transform.scale(raw_img, (int(target_height * aspect), target_height))
            textures.append(scaled_img)
        except Exception as e:
            print(f"[Engine] Fallo cargando balcon ({i}): {e}")
            fallback = pygame.Surface((target_height * 3, target_height))
            fallback.fill((150, 150, 150))
            textures.append(fallback)
    return textures

class Platform(pygame.Rect):
    def __init__(self, x, y, texture_index):
        self.image = PLATFORM_TEXTURES[texture_index % len(PLATFORM_TEXTURES)]
        # Super init como un Rect que calza exactamente con la imagen
        super().__init__(x, y, self.image.get_width(), self.image.get_height())




# ==========================================
# 4. ENTIDADES SECUNDARIAS (Enemigos y Proyectiles)
# ==========================================
class Projectile(pygame.sprite.Sprite):
    _CACHED_SURF = None
    def __init__(self, x, y, facing_right):
        super().__init__()
        if Projectile._CACHED_SURF is None:
            Projectile._CACHED_SURF = pygame.Surface((40, 40), pygame.SRCALPHA)
            pygame.draw.circle(Projectile._CACHED_SURF, (255, 255, 0), (20, 20), 20)
            pygame.draw.circle(Projectile._CACHED_SURF, (255, 200, 0), (20, 20), 14)
            pygame.draw.line(Projectile._CACHED_SURF, (255,255,255), (20,5), (20,35), 2)
            pygame.draw.line(Projectile._CACHED_SURF, (255,255,255), (5,20), (35,20), 2)
        self.image = Projectile._CACHED_SURF
        self.rect = self.image.get_rect()
        self.rect.center = (x, y)
        self.velocity_x = 18 if facing_right else -18

    def update(self):
        self.rect.x += self.velocity_x

class EnemyProjectile(pygame.sprite.Sprite):
    _CACHED_SURF = None
    def __init__(self, x, y, direction_x):
        super().__init__()
        if EnemyProjectile._CACHED_SURF is None:
            EnemyProjectile._CACHED_SURF = pygame.Surface((20, 20), pygame.SRCALPHA)
            pygame.draw.circle(EnemyProjectile._CACHED_SURF, (255, 50, 50), (10, 10), 10)
            pygame.draw.circle(EnemyProjectile._CACHED_SURF, (255, 100, 0), (10, 10), 6)
        self.image = EnemyProjectile._CACHED_SURF
        self.rect = self.image.get_rect()
        self.rect.center = (x, y)
        self.velocity_x = direction_x * 8
        
    def update(self):
        self.rect.x += self.velocity_x

class Enemy(pygame.sprite.Sprite):
    _CACHED_IMAGES = {}

    def __init__(self, x, y):
        super().__init__()
        self.velocity_x = 0
        self.velocity_y = 0
        self.image = None
        self.rect = None
        self._visual_offset_y = 0

    def _lazy_load_image(self, asset_name, scale):
        key = f"{asset_name}_{scale}"
        if key not in Enemy._CACHED_IMAGES:
            try:
                img = pygame.image.load(asset_name).convert_alpha()
                Enemy._CACHED_IMAGES[key] = pygame.transform.scale(img, scale)
            except Exception as e:
                print(f"[Enemy] Error cargando sprite {asset_name}: {e}")
                fallback = pygame.Surface(scale)
                fallback.fill((255, 0, 255))
                Enemy._CACHED_IMAGES[key] = fallback
        return Enemy._CACHED_IMAGES[key]

    def update(self, *args, **kwargs):
        pass

    def draw(self, surface, camera_x):
        if not self.image: return
        img = self.image
        # Mirando a la derecha (si la velocidad es positiva o si está marcado explícitamente)
        facing_right = getattr(self, 'facing_right', self.velocity_x > 0)
        if facing_right:
            img = pygame.transform.flip(self.image, True, False)
        draw_pos = (self.rect.x - camera_x, self.rect.y + self._visual_offset_y)
        surface.blit(img, draw_pos)


class FlowerEnemy(Enemy):
    def __init__(self, x, y):
        super().__init__(x, y)
        self.walk_frames = []
        try:
            for i in range(1, 14):
                path = f"components/Flor Caminante/Flor Caminante ({i}).png"
                img = self._lazy_load_image(path, (97, 119))
                self.walk_frames.append(img)
        except Exception as e:
            print(f"[Enemy] Fallback Flor Caminante: {e}")
            fallback = pygame.Surface((97, 119))
            fallback.fill((100, 200, 100))
            self.walk_frames = [fallback]

        self.frame_index = 0
        self.animation_speed = 0.18 # Timming ajustado. Camina a (V=3), levemente más lento que Echo (V=4) => 10.8 FPS Visual (1.2s por zancada pesada)
        self.image = self.walk_frames[0]
        
        self.rect = self.image.get_rect()
        self.rect.centerx = x
        self.rect.bottom = y
        self.velocity_x = -3
        self.velocity_y = 0
        self.gravity = 0.65
        self.facing_right = False

    def update(self, visible_platforms, **kwargs):
        self.rect.x += self.velocity_x
        self.velocity_y += self.gravity
        self.rect.y += int(self.velocity_y)
        
        on_ground = False
        current_platform = None
        
        if self.velocity_y >= 0:
            for plat in visible_platforms:
                if (self.rect.bottom >= plat.top and 
                    self.rect.bottom <= plat.top + 30 and 
                    self.rect.right > plat.left and 
                    self.rect.left < plat.right):
                    self.rect.bottom = plat.top + 20 # Hundido para contacto visual
                    self.velocity_y = 0.0
                    on_ground = True
                    current_platform = plat
                    break
        
        if not on_ground and self.rect.bottom >= GROUND_Y + 20:
            self.rect.bottom = GROUND_Y + 20
            self.velocity_y = 0.0
            on_ground = True
            
        # Detección de Bordes Inteligente en Plataformas
        if on_ground and current_platform:
            if self.rect.right - 10 > current_platform.right or self.rect.left + 10 < current_platform.left:
                self.velocity_x *= -1
                self.rect.x += self.velocity_x * 2
        
        # Actualizar orientación visual
        self.facing_right = self.velocity_x > 0
        
        # Animación de las patas y Fliping hacia Echo
        self.frame_index += self.animation_speed
        if self.frame_index >= len(self.walk_frames):
            self.frame_index = 0
            
        current_frame = self.walk_frames[int(self.frame_index)]
        self.image = current_frame if self.facing_right else pygame.transform.flip(current_frame, True, False)


class GargoyleEnemy(Enemy):
    def __init__(self, x, y):
        super().__init__(x, y)
        self.flight_frames = []
        try:
            for i in range(1, 12):
                path = f"components/gargola/gargola ({i}).png"
                img = self._lazy_load_image(path, (110, 100))
                self.flight_frames.append(img)
        except Exception as e:
            print(f"[Enemy] Fallback Gárgola: {e}")
            fallback = pygame.Surface((110, 100))
            fallback.fill((100, 20, 100))
            self.flight_frames = [fallback]

        self.frame_index = 0
        self.animation_speed = 0.25 # Timming ajustado. Alas de piedra: 15 FPS Visual (0.73s por aleteo) - Menos vibración, más peso
        self.image = self.flight_frames[0]
        
        self.rect = self.image.get_rect()
        self.rect.centerx = x
        self.rect.centery = y - 100
        self.base_y = self.rect.centery
        self.velocity_x = -2
        self.anim_tick = random.random() * 10
        self.gravity = 0 # No cae

    def update(self, player_x, **kwargs):
        self.rect.x += self.velocity_x
        self.anim_tick += 0.05
        self.rect.centery = self.base_y + int(math.sin(self.anim_tick) * 50)
        
        # Deadzone de 20px
        if abs(self.rect.centerx - player_x) > 20:
            if self.rect.centerx > player_x:
                self.velocity_x = -2
            else:
                self.velocity_x = 2
                
        # Rotación visual adaptativa
        self.facing_right = self.velocity_x > 0
        
        # Animación secuencial de aleteo y Fliping
        self.frame_index += self.animation_speed
        if self.frame_index >= len(self.flight_frames):
            self.frame_index = 0
            
        current_frame = self.flight_frames[int(self.frame_index)]
        self.image = current_frame if self.facing_right else pygame.transform.flip(current_frame, True, False)


class ShooterFlower(Enemy):
    def __init__(self, x, y):
        super().__init__(x, y)
        self.idle_frames = []
        try:
            for i in range(1, 12):
                path = f"components/Flor Tiradora/Flor Tiradora ({i}).png"
                img = self._lazy_load_image(path, (81, 119))
                self.idle_frames.append(img)
        except Exception as e:
            print(f"[Enemy] Fallback Flor Tiradora: {e}")
            fallback = pygame.Surface((81, 119))
            fallback.fill((200, 100, 100))
            self.idle_frames = [fallback]

        self.frame_index = 0
        self.animation_speed = 0.10 # Timming ajustado. Respiración vegetal (Idle lento): 6 FPS Visual (casi 2 segundos por ciclo)
        self.image = self.idle_frames[0]
        
        self.rect = self.image.get_rect()
        self.rect.centerx = x
        self.rect.bottom = y
        self.gravity = 0.65
        self.velocity_x = 0
        self.last_shot_time = pygame.time.get_ticks()
        self.facing_right = False

    def update(self, visible_platforms, player_x, enemy_projectiles, **kwargs):
        # Asentamiento por gravedad (No patrulla horizontal)
        self.velocity_y += self.gravity
        self.rect.y += int(self.velocity_y)
        
        if self.velocity_y >= 0:
            for plat in visible_platforms:
                if (self.rect.bottom >= plat.top and 
                    self.rect.bottom <= plat.top + 30 and 
                    self.rect.right > plat.left and 
                    self.rect.left < plat.right):
                    self.rect.bottom = plat.top + 20 # Hundido
                    self.velocity_y = 0.0
                    break
        if self.rect.bottom >= GROUND_Y + 20:
            self.rect.bottom = GROUND_Y + 20
            self.velocity_y = 0.0
            
        # Girar para mirar al jugador
        self.facing_right = player_x > self.rect.centerx
        
        # Animación de respiración e Inteligencia de Mirada
        self.frame_index += self.animation_speed
        if self.frame_index >= len(self.idle_frames):
            self.frame_index = 0
            
        current_frame = self.idle_frames[int(self.frame_index)]
        self.image = current_frame if self.facing_right else pygame.transform.flip(current_frame, True, False)

        # Mecánica de disparo estática
        now = pygame.time.get_ticks()
        if now - self.last_shot_time > 7500:
            self.last_shot_time = now
            direction = 1 if player_x > self.rect.centerx else -1
            enemy_projectiles.append(EnemyProjectile(self.rect.centerx, self.rect.centery, direction))


# ==========================================
# 5. CLASE PLAYER — HD-2D con bob procedural
# ==========================================
class Player(pygame.sprite.Sprite):
    def __init__(self, ground_y, platforms):
        super().__init__()

        # ── Carga de motor de animación (Pre-cálculo masivo) ───────────
        self.frames_right = []
        self.frames_left = []
        self.attack_right = []
        self.attack_left = []
        
        try:
            for i in range(1, 14):
                path = f"components/echo/echo ({i}).png"
                img = pygame.image.load(path).convert_alpha()
                base_scaled = pygame.transform.scale(img, (90, 140))
                
                # Pre-calcular variaciones
                base_left = pygame.transform.flip(base_scaled, True, False)
                
                atk_right = base_scaled.copy()
                atk_right.fill((255, 50, 50, 0), special_flags=pygame.BLEND_RGB_ADD)
                
                atk_left = base_left.copy()
                atk_left.fill((255, 50, 50, 0), special_flags=pygame.BLEND_RGB_ADD)
                
                self.frames_right.append(base_scaled)
                self.frames_left.append(base_left)
                self.attack_right.append(atk_right)
                self.attack_left.append(atk_left)
            print("[Player] 13 cuadros de animación cargados (" + str(len(self.frames_right)) + ")")
        except Exception as e:
            print(f"[Player] Fallback de Animación: {e}")
            fallback_surf = pygame.Surface((90, 140))
            fallback_surf.fill((150, 150, 150))
            self.frames_right = [fallback_surf]
            self.frames_left = [fallback_surf]
            self.attack_right = [fallback_surf]
            self.attack_left = [fallback_surf]

        self.frame_index = 0
        self.animation_speed = 0.25 # Timming ajustado. Echo V=4 -> 15 FPS Visual (0.86s por ciclo completo). Más dinámico.
        self.image = self.frames_right[self.frame_index]
        self.rect       = self.image.get_rect()
        self.rect.x     = 80
        self.rect.y     = ground_y - self.rect.height

        # ── Físicas ──────────────────────────────────────────────────────────
        self.velocity_y  = 0.0
        self.velocity_x  = 0
        self.target_velocity_x = 0  # Velocidad deseada (para recuperar el ritmo tras knockback)
        self.speed       = 4
        self.gravity     = 0.65
        self.jump_power  = -24 # Incrementado para mayor altura
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

        # ── Animación estructural ─────────────────────────────────────────────
        # Ya no usamos _bob_offset porque la animación provee su propio movimiento
        self._bob_offset = 0

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
            if self.is_jumping: # Reseteo absoluto al aterrizar
                self.velocity_x = self.target_velocity_x
            self.is_jumping  = False
            on_ground        = True

        # 4. Colisión con plataformas flotantes sólidas y de suelo (Culling optimizado)
        if self.velocity_y >= 0:
            for plat in visible_platforms:
                if (self.rect.bottom >= plat.top
                        and self.rect.bottom <= plat.top + 20
                        and self.rect.right  > plat.left + 4
                        and self.rect.left   < plat.right - 4):
                    self.rect.bottom = plat.top
                    self.velocity_y  = 0.0
                    if self.is_jumping: # Reseteo absoluto al aterrizar
                        self.velocity_x = self.target_velocity_x
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

        # 7. Ciclo de Animación por cuadros
        if self.velocity_x != 0 and on_ground:
            self.frame_index += self.animation_speed
            if self.frame_index >= len(self.frames_right):
                self.frame_index = 0
        else:
            self.frame_index = 0 # Postura estática de descanso

        # Update variables de acción y disparo
        if self.velocity_x > 0: self.facing_right = True
        elif self.velocity_x < 0: self.facing_right = False
        
        if self.invulnerable_timer > 0:
            self.invulnerable_timer -= 1
            
        for p in self.projectiles[:]:
            p.update()

        # 8. Render de memoria O(1)
        target_list = self.frames_right
        if self.is_attacking:
            target_list = self.attack_right if self.facing_right else self.attack_left
            if self.attack_timer > 0:
                self.attack_timer -= 1
            else:
                self.is_attacking = False
        else:
            target_list = self.frames_right if self.facing_right else self.frames_left

        self.image = target_list[int(self.frame_index)]

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
            # Salto largo si estamos en movimiento
            if self.velocity_x != 0:
                self.velocity_x = self.speed * 1.5
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
             last_cmd_time, debounce_secs, lives, hud_cache):
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

    # 3. Texto del comando reconocido (con sombra para legibilidad y caché de render)
    if hud_cache["last_command"] != last_command or hud_cache["last_color"] != cmd_color:
        cmd_text = last_command[:26]   # Truncar si es muy largo
        hud_cache["shadow_surf"] = font_md.render(cmd_text, True, (0, 0, 0))
        hud_cache["cmd_surf"]    = font_md.render(cmd_text, True, cmd_color)
        hud_cache["last_command"] = last_command
        hud_cache["last_color"] = cmd_color
        
    screen.blit(hud_cache["shadow_surf"], (HX + 15, HY + 41))
    screen.blit(hud_cache["cmd_surf"], (HX + 14, HY + 40))

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

    # ── GENERACIÓN DEL NUEVO FONDO Y BALCONES MUNDIALES ───────────────────────
    global PLATFORM_TEXTURES
    PLATFORM_TEXTURES = load_platform_textures(45) # Altura maestra de balcones para colisión precisa

    try:
        raw_bg = pygame.image.load("components/Elementos_Espaciales1/Fondo.png").convert()
        # Escalar preservando aspecto para ajustarse a 720p sin distorsionarse
        aspect_bg = raw_bg.get_width() / raw_bg.get_height()
        bg_espacial = pygame.transform.scale(raw_bg, (int(HEIGHT * aspect_bg), HEIGHT))
    except Exception as e:
        print(f"[Fondo] Falló cargando el fondo masivo: {e}")
        bg_espacial = pygame.Surface((WIDTH, HEIGHT))
        bg_espacial.fill((40, 10, 60))

    rng = random.Random(101)
    
    # 1. Plataformas Universales (Balcones Físicos Object-Oriented)
    platforms = []
    pos_x = 240
    while pos_x < 31200:
        pw_gap = rng.randint(180, 400) # Hueco al siguiente
        py = GROUND_Y - rng.randint(120, 450) # Elevaciones drásticas para ambiente espacial flotante
        texture_idx = rng.randint(0, 5) # Texturas 0-5 (balcones 1 a 6)
        
        # Generar plataforma inteligente
        new_plat = Platform(pos_x, py, texture_idx)
        platforms.append(new_plat)
        pos_x += new_plat.width + pw_gap
        
    platforms_x = [p.x for p in platforms] # Lista K-V para bisect rápido

    # Suelo Global (Un único chunk imaginario ancho para caer)
    ground_chunks = [pygame.Rect(-1000, GROUND_Y, 40000, 100)]
    ground_xs = [-1000]

    # 4. Peligros y Enemigos 
    LEVEL_END_X = 31000
    victory = False

    enemies = []

    
    # Spawn de Tiradoras Estáticas (Reemplazo de Hazards)
    hx = 1200
    while hx < LEVEL_END_X - 1000:
        enemies.append(ShooterFlower(hx, GROUND_Y))
        hx += rng.randint(800, 2500)

    # Spawn Dinámico de Caminantes y Voladoras
    ex = 1000
    while ex < LEVEL_END_X - 1000:
        flight_y = GROUND_Y - rng.randint(150, 450)
        enemies.append(GargoyleEnemy(ex, flight_y))
        ex += rng.randint(700, 1600)
        
        # Añadir caminantes en plataformas
        if rng.random() > 0.4:
            plat = rng.choice(platforms)
            if plat.x > 1000:
                enemies.append(FlowerEnemy(plat.centerx, plat.top))
                
    enemy_projectiles = []

    # ── PRE-RENDER CACHE ────────────────────────────────────
    hud_bg     = build_hud_bg()
    
    # ── HUD Text Cache ──────────────────────────────────────
    hud_cache = {"last_command": None, "last_color": None, "shadow_surf": None, "cmd_surf": None}

    # ── Cache del Overlay de Pausa ──────────────────────────
    pause_overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    pause_overlay.fill((0, 0, 0, 100))
    try:
        f_pause = pygame.font.SysFont("Consolas", 60, bold=True)
    except:
        f_pause = pygame.font.Font(None, 80)
    lbl_pause = f_pause.render("PAUSA", True, (255, 255, 255))
    pause_overlay.blit(lbl_pause, (WIDTH // 2 - lbl_pause.get_width() // 2, HEIGHT // 2 - lbl_pause.get_height() // 2))

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
    paused        = False

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
                if event.key == pygame.K_SPACE:
                    paused = not paused

        if not paused:
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

            idx_start_gnd = bisect.bisect_left(ground_xs, camera_x - 4000)
            idx_end_gnd   = bisect.bisect_right(ground_xs, camera_x + WIDTH)
            visible_grounds = ground_chunks[max(0, idx_start_gnd):idx_end_gnd]

            # Culling Enemy Projectiles (Memory Leak Prevention)
            for ep in enemy_projectiles[:]:
                ep.update()
                hit_plat = ep.rect.collidelist(visible_platforms) != -1
                out_of_bounds = ep.rect.x < camera_x - 100 or ep.rect.x > camera_x + WIDTH + 100
                hit_player = ep.rect.colliderect(player.rect)
                
                if hit_player:
                    if player.take_damage(): lives -= 1
                if hit_plat or out_of_bounds or hit_player:
                    if ep in enemy_projectiles: enemy_projectiles.remove(ep)
            
            # ── INTERACCIONES Y LÓGICA (Solo si no hemos ganado) ──────────────────
            if player.rect.centerx >= LEVEL_END_X and not victory:
                victory = True
                player.stop()

            if not victory:
                # Lógica de Enemigos Polimórficos
                for e in enemies[:]:
                    if camera_x - 200 < e.rect.x < camera_x + WIDTH + 200:
                        e.update(visible_platforms=visible_platforms, player_x=player.rect.centerx, enemy_projectiles=enemy_projectiles)
                        
                        # Colisión Jugador vs Enemigo
                        if e.rect.colliderect(player.rect):
                            if player.take_damage():
                                lives -= 1
                        
                        # Colisión Proyectil vs Enemigo
                        for p in player.projectiles[:]:
                            if p.rect.colliderect(e.rect):
                                if p in player.projectiles: player.projectiles.remove(p)
                                if e in enemies: enemies.remove(e)

                # Mantenimiento de Proyectiles del Jugador
                for p in player.projectiles[:]:
                    hit_plat = p.rect.collidelist(visible_platforms) != -1
                    out_of_bounds = p.rect.x < camera_x - 300 or p.rect.x > camera_x + WIDTH + 300
                    if hit_plat or out_of_bounds:
                        if p in player.projectiles: player.projectiles.remove(p)
                        
                # Update físico principal del jugador
                player.update(visible_platforms)
                if lives <= 0:
                    pass # Aquí iría lógica de GameOver. Por ahora se quedará vivo a 0.

        # ── RENDER (FONDO ESPACIAL PANORÁMICO PARALLAX) ───────────────────────
        # Limpiar ghosting previo a dibujar
        screen.fill((10, 5, 20)) 
        
        bg_w = bg_espacial.get_width()
        # Módulo corregido: Asegura que el valor sea estrictamente negativo para desplazar hacia la izquierda
        bg_scroll = -((camera_x * 0.15) % bg_w)
        
        screen.blit(bg_espacial, (bg_scroll, 0))
        # Dibujo de continuación asegurando cubrir la resolución entera WIDTH
        if bg_scroll + bg_w < WIDTH:
            screen.blit(bg_espacial, (bg_scroll + bg_w, 0))

        # 3. Suelo Visible (Espacio Físico Local)
        # Render invisible/transparente. La imagen Fondo provee el suelo visual.
        # ...pero lo podemos visualizar si no existe bg_espacial
        
        # 4. Plataformas Flotantes Visibles (Balcones de Pool)
        for plat in visible_platforms:
            screen.blit(plat.image, (plat.x - camera_x, plat.y))
                                 
        # (Peligos/Hazards estáticos reemplazados por ShooterFlower)
        
        # 6. Enemigos (Renderizado con IA y Flip)
        for e in enemies:
            if camera_x - 200 < e.rect.x < camera_x + WIDTH + 200:
                e.draw(screen, camera_x)
                
        # 7. Proyectiles
        for p in player.projectiles:
            screen.blit(p.image, (p.rect.x - camera_x, p.rect.y))
            
        for ep in enemy_projectiles:
            screen.blit(ep.image, (ep.rect.x - camera_x, ep.rect.y))
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

        # Capa UI: Cartel Pausa
        if paused:
            screen.blit(pause_overlay, (0, 0))

        # HUD dinámico (solo texto blit o render si cambia el caché)
        draw_hud(screen, hud_bg, font_sm, font_md,
                 last_command, cmd_color, last_cmd_time, DEBOUNCE_SECS, lives, hud_cache)

        pygame.display.flip()
        clock.tick(FPS)

    print("[Pygame] Apagando el juego...")
    voice_process.terminate()
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
