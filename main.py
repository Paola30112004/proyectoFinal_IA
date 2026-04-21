import sys
import os
import json
import time
import math
import bisect
import multiprocessing
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

PLATFORM_TEXTURES = [] # Pool global para plataformas
TORRE_TEXTURES = []  # Pool global para las torres
def load_torre_textures():
    """Carga las 3 texturas Torre_Balcon en RAM una sola vez."""
    textures = []
    for i in range(1, 4):
        try:
            raw_img = pygame.image.load(f"components/Elementos_Espaciales1/Torre_Balcon ({i}).png").convert_alpha()
            target_h = 250
            aspect = raw_img.get_width() / raw_img.get_height()
            scaled_img = pygame.transform.scale(raw_img, (int(target_h * aspect), target_h))
            textures.append(scaled_img)
        except Exception as e:
            print(f"[Engine] Fallo cargando Torre_Balcon ({i}): {e}")
            fallback = pygame.Surface((80, 250))
            fallback.fill((120, 60, 180))
            textures.append(fallback)
    return textures

class Platform(pygame.Rect):
    def __init__(self, x, y, texture_index):
        self.image = PLATFORM_TEXTURES[texture_index % len(PLATFORM_TEXTURES)]
        # Super init como un Rect que calza exactamente con la imagen
        super().__init__(x, y, self.image.get_width(), self.image.get_height())

class TorreBalcon:
    """Torre decorativa anclada al suelo real con 40px enterrada para integración visual."""
    def __init__(self, x, texture_index, floor_y=None):
        self.img    = TORRE_TEXTURES[texture_index % len(TORRE_TEXTURES)]
        self.x      = x
        _floor      = floor_y if floor_y is not None else GROUND_Y
        # Enterrar 40px en el suelo para que se vea integrada al terreno
        self.y      = _floor - self.img.get_height() + 40
        self.width  = self.img.get_width()
        self.height = self.img.get_height()
        # El balcón superior de la torre (plataforma física) ocupa el 18% superior de la imagen
        balcon_h = max(30, int(self.height * 0.18))
        self.platform = Platform.__new__(Platform)
        pygame.Rect.__init__(self.platform, x, self.y, self.width, balcon_h)
        self.platform.image = self.img.subsurface((0, 0, self.width, balcon_h)).copy()




# ==========================================
# 4. ENTIDADES SECUNDARIAS (Enemigos y Proyectiles)
# ==========================================
class Projectile(pygame.sprite.Sprite):
    _CACHED_SURFS = []  # [img0_R, img0_L, img1_R, img1_L]
    def __init__(self, x, y, facing_right, img_index):
        super().__init__()
        if not Projectile._CACHED_SURFS:
            for i in range(1, 3):
                img = pygame.image.load(f"components/echo/Echo_Disparos ({i}).png").convert_alpha()
                target_h = 80
                aspect = img.get_width() / img.get_height()
                surf_r = pygame.transform.scale(img, (int(target_h * aspect), target_h))
                surf_l = pygame.transform.flip(surf_r, True, False)  # Versión espejada izquierda
                Projectile._CACHED_SURFS.append(surf_r)  # índice par   = mirando derecha
                Projectile._CACHED_SURFS.append(surf_l)  # índice impar = mirando izquierda
        
        # FIX #2: Seleccionar imagen según facing_right (igual que EnemyProjectile)
        base_idx = (img_index % 2) * 2
        self.image = Projectile._CACHED_SURFS[base_idx] if facing_right else Projectile._CACHED_SURFS[base_idx + 1]
        self.rect = self.image.get_rect()
        self.rect.center = (x, y)
        self.start_x = x
        self.start_y = y
        self.velocity_x = 18 if facing_right else -18
        self.tick = 0  # FIX #4: contador de ciclos determinista

    def update(self):
        self.rect.x += self.velocity_x
        # FIX #4: sin(tick) en vez de get_ticks() — sin cruce de interfaz CFFI por frame
        self.tick += 1
        self.rect.centery = self.start_y + int(math.sin(self.tick * 0.18) * 15)

class EnemyProjectile(pygame.sprite.Sprite):
    _CACHED_SURFS = []  # [img0_R, img0_L, img1_R, img1_L]
    def __init__(self, x, y, direction_x, img_index):
        super().__init__()
        if not EnemyProjectile._CACHED_SURFS:
            for i in range(1, 3):
                img = pygame.image.load(f"components/Flor Tiradora/FlorTiradora_Disparos ({i}).png").convert_alpha()
                # Resolución refinada: más pequeño (40px) preservando forma
                target_h = 40
                aspect = img.get_width() / img.get_height()
                surf_r = pygame.transform.scale(img, (int(target_h * aspect), target_h))
                surf_l = pygame.transform.flip(surf_r, True, False)
                EnemyProjectile._CACHED_SURFS.append(surf_r) # Derecha
                EnemyProjectile._CACHED_SURFS.append(surf_l) # Izquierda
        
        # Selección de giro: Si direction_x < 0 (viaja a la izq hacia Echo), usa la versión Left
        base_idx = (img_index % 2) * 2
        going_right = direction_x > 0
        self.image = EnemyProjectile._CACHED_SURFS[base_idx] if going_right else EnemyProjectile._CACHED_SURFS[base_idx + 1]
        self.rect = self.image.get_rect()
        self.rect.center = (x, y)
        self.start_y = y
        self.velocity_x = direction_x * 8
        # FIX #4: contador de ciclos, sin cruce de interfaz
        self.tick = 0
        
    def update(self):
        self.rect.x += self.velocity_x
        self.tick += 1
        self.rect.centery = self.start_y + int(math.sin(self.tick * 0.15) * 15)

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
        key_right = f"{asset_name}_{scale}_R"
        key_left = f"{asset_name}_{scale}_L"
        
        if key_right not in Enemy._CACHED_IMAGES:
            try:
                img = pygame.image.load(asset_name).convert_alpha()
                base_scaled = pygame.transform.scale(img, scale)
                # La imagen base mira a la DERECHA — guardar correctamente
                Enemy._CACHED_IMAGES[key_right] = base_scaled
                Enemy._CACHED_IMAGES[key_left] = pygame.transform.flip(base_scaled, True, False)
            except Exception as e:
                print(f"[Enemy] Error cargando sprite {asset_name}: {e}")
                fallback = pygame.Surface(scale)
                fallback.fill((255, 0, 255))
                Enemy._CACHED_IMAGES[key_left] = fallback
                Enemy._CACHED_IMAGES[key_right] = fallback
                
        # Retorna una tupla (Left_Surface, Right_Surface)
        return Enemy._CACHED_IMAGES[key_left], Enemy._CACHED_IMAGES[key_right]

    def update(self, *args, **kwargs):
        pass

    def draw(self, surface, camera_x):
        if not self.image: return
        # Enemigos siempre miran a la izquierda (imagen original sin voltear)
        draw_pos = (self.rect.x - camera_x, self.rect.y + self._visual_offset_y)
        surface.blit(self.image, draw_pos)


class FlowerEnemy(Enemy):
    def __init__(self, x, y):
        super().__init__(x, y)
        self.walk_frames_left = []
        self.walk_frames_right = []
        try:
            for i in range(1, 14):
                path = f"components/Flor Caminante/Flor Caminante ({i}).png"
                img_l, img_r = self._lazy_load_image(path, (97, 119))
                self.walk_frames_left.append(img_l)
                self.walk_frames_right.append(img_r)
        except Exception as e:
            print(f"[Enemy] Fallback Flor Caminante: {e}")
            fallback = pygame.Surface((97, 119))
            fallback.fill((100, 200, 100))
            self.walk_frames_left = [fallback]
            self.walk_frames_right = [fallback]

        self.frame_index = 0
        self.animation_speed = 0.18 # Timming ajustado. Camina a (V=3), levemente más lento que Echo (V=4) => 10.8 FPS Visual (1.2s por zancada pesada)
        self.image = self.walk_frames_left[0]
        
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
        
        # Detectar suelo real y huecos con físicas estrictas
        visible_ground = kwargs.get('visible_ground', [])
        ground_offset  = kwargs.get('ground_offset', 115)
        
        if self.velocity_y >= 0 and not on_ground:
            for grect in visible_ground:
                real_top = grect.top + ground_offset
                if (self.rect.bottom >= real_top and 
                    self.rect.bottom <= real_top + 30 and 
                    self.rect.right > grect.left and 
                    self.rect.left < grect.right):
                    self.rect.bottom = real_top
                    self.velocity_y = 0.0
                    on_ground = True
                    current_platform = grect
                    break
            
        # Detección de Bordes Inteligente en Plataformas (Con filtro de vector direccional para evitar loops de vibración O(1))
        if on_ground and current_platform:
            if self.rect.right - 10 > current_platform.right and self.velocity_x > 0:
                self.velocity_x *= -1
            elif self.rect.left + 10 < current_platform.left and self.velocity_x < 0:
                self.velocity_x *= -1
        
        # Actualizar orientación visual
        self.facing_right = self.velocity_x > 0
        
        # Animación de las patas (Pre-calculada O(1))
        self.frame_index += self.animation_speed
        if self.frame_index >= len(self.walk_frames_left):
            self.frame_index = 0
            
        target_list = self.walk_frames_right if self.facing_right else self.walk_frames_left
        self.image = target_list[int(self.frame_index)]


class GargoyleEnemy(Enemy):
    def __init__(self, x, y):
        super().__init__(x, y)
        self.flight_frames_left = []
        self.flight_frames_right = []
        try:
            for i in range(1, 12):
                path = f"components/gargola/gargola ({i}).png"
                img_l, img_r = self._lazy_load_image(path, (110, 100))
                self.flight_frames_left.append(img_l)
                self.flight_frames_right.append(img_r)
        except Exception as e:
            print(f"[Enemy] Fallback Gárgola: {e}")
            fallback = pygame.Surface((110, 100))
            fallback.fill((100, 20, 100))
            self.flight_frames_left = [fallback]
            self.flight_frames_right = [fallback]

        self.frame_index = 0
        self.animation_speed = 0.25 # Timming ajustado. Alas de piedra: 15 FPS Visual (0.73s por aleteo) - Menos vibración, más peso
        self.image = self.flight_frames_left[0]
        
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
        
        # Animación secuencial de aleteo O(1)
        self.frame_index += self.animation_speed
        if self.frame_index >= len(self.flight_frames_left):
            self.frame_index = 0
            
        target_list = self.flight_frames_right if self.facing_right else self.flight_frames_left
        self.image = target_list[int(self.frame_index)]


class ShooterFlower(Enemy):
    def __init__(self, x, y):
        super().__init__(x, y)
        self.idle_frames_left = []
        self.idle_frames_right = []
        try:
            for i in range(1, 12):
                path = f"components/Flor Tiradora/Flor Tiradora ({i}).png"
                img_l, img_r = self._lazy_load_image(path, (81, 119))
                self.idle_frames_left.append(img_l)
                self.idle_frames_right.append(img_r)
        except Exception as e:
            print(f"[Enemy] Fallback Flor Tiradora: {e}")
            fallback = pygame.Surface((81, 119))
            fallback.fill((200, 100, 100))
            self.idle_frames_left = [fallback]
            self.idle_frames_right = [fallback]

        self.frame_index = 0
        self.animation_speed = 0.10 # Timming ajustado. Respiración vegetal (Idle lento): 6 FPS Visual (casi 2 segundos por ciclo)
        self.shot_count = 0
        self.image = self.idle_frames_left[0]
        
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
        
        # Detectar suelo real (si se pasa en kwargs)
        floor_y = kwargs.get('floor_y', GROUND_Y + 20)
        
        if self.velocity_y >= 0:
            for plat in visible_platforms:
                if (self.rect.bottom >= plat.top and 
                    self.rect.bottom <= plat.top + 30 and 
                    self.rect.right > plat.left and 
                    self.rect.left < plat.right):
                    self.rect.bottom = plat.top + 20 # Hundido en plataforma
                    self.velocity_y = 0.0
                    break
        
        if self.rect.bottom >= floor_y:
            self.rect.bottom = floor_y
            self.velocity_y = 0.0
            
        # Girar para mirar al jugador
        self.facing_right = player_x > self.rect.centerx
        
        # Animación de respiración e Inteligencia de Mirada O(1)
        self.frame_index += self.animation_speed
        if self.frame_index >= len(self.idle_frames_left):
            self.frame_index = 0
            
        target_list = self.idle_frames_right if self.facing_right else self.idle_frames_left
        self.image = target_list[int(self.frame_index)]

        # Mecánica de disparo estática
        now = pygame.time.get_ticks()
        # 15% más lento: 4000 * 1.15 = 4600 ms
        if now - self.last_shot_time > 4600:
            self.last_shot_time = now
            direction = 1 if player_x > self.rect.centerx else -1
            # Spawn ligeramente más alto (-30) para evitar colisión con su propia plataforma
            enemy_projectiles.append(EnemyProjectile(self.rect.centerx, self.rect.centery - 30, direction, self.shot_count))
            self.shot_count += 1


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
            import os
            for i in range(1, 14):
                # Saltar frames que no existen en disco en vez de tirar excepción
                found_path = None
                for fmt in [f"echo ({i}).png", f"echo({i}).png"]:
                    p = os.path.join("components/echo", fmt)
                    if os.path.exists(p):
                        found_path = p
                        break
                
                if not found_path:
                    continue  # Frame faltante (ej: echo (2).png) → simplemente saltamos
                    
                img = pygame.image.load(found_path).convert_alpha()
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
            
            if not self.frames_right:
                raise RuntimeError("No se cargó ningún frame de Echo")
            print(f"[Player] {len(self.frames_right)} cuadros de animación cargados")
        except Exception as e:
            print(f"[Player] Fallback de Animación: {e}")
            fallback_surf = pygame.Surface((90, 140))
            fallback_surf.fill((150, 150, 150))
            self.frames_right = [fallback_surf]
            self.frames_left = [fallback_surf]
            self.attack_right = [fallback_surf]
            self.attack_left = [fallback_surf]

        self.frame_index = 0
        self.animation_speed = 0.45 # Estilo Cartoon: Muy rápido
        self.shot_count = 0
        self.image = self.frames_right[self.frame_index]
        self.rect       = self.image.get_rect()
        self.rect.x     = 80
        self.rect.y     = ground_y - self.rect.height

        # ── Físicas ──────────────────────────────────────────────────────────
        self.velocity_y  = 0.0
        self.velocity_x  = 0
        self.target_velocity_x = 0  # Velocidad deseada (para recuperar el ritmo tras knockback)
        self.speed       = 5  # +25% de velocidad (antes 4)
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

        # 3. Colisión con bloques de suelo — O(log N) con bisect
        on_ground = False
        gblocks = getattr(self, '_ground_blocks', [])
        g_tops  = getattr(self, '_ground_tops', [])  # pre-ordenado
        # GROUND_OFFSET sincronizado con main(): 115px
        G_OFFSET = 115
        if self.velocity_y >= 0 and gblocks and g_tops:
            tol = max(36, abs(int(self.velocity_y)) + 6)
            # bisect sobre los tops reales para encontar bloques candidatos
            target_top = self.rect.bottom - tol
            lo = bisect.bisect_left(g_tops, target_top)
            hi = bisect.bisect_right(g_tops, self.rect.bottom + 2)
            for gi in range(max(0, lo - 1), min(len(gblocks), hi + 1)):
                grect = gblocks[gi]
                real_top = grect.top + G_OFFSET
                if (self.rect.bottom >= real_top
                        and self.rect.bottom <= real_top + tol
                        and self.rect.right  >  grect.left + 4
                        and self.rect.left   <  grect.right - 4):
                    self.rect.bottom = real_top
                    self.velocity_y  = 0.0
                    if self.is_jumping:
                        self.velocity_x = self.target_velocity_x
                    self.is_jumping  = False
                    on_ground        = True
                    break
        elif self.velocity_y >= 0 and gblocks and not g_tops:
            # Fallback iterat si no hay lista de tops
            G_OFFSET = 115
            tol = max(36, abs(int(self.velocity_y)) + 6)
            for grect in gblocks:
                real_top = grect.top + G_OFFSET
                if (self.rect.bottom >= real_top
                        and self.rect.bottom <= real_top + tol
                        and self.rect.right  >  grect.left + 4
                        and self.rect.left   <  grect.right - 4):
                    self.rect.bottom = real_top
                    self.velocity_y  = 0.0
                    if self.is_jumping:
                        self.velocity_x = self.target_velocity_x
                    self.is_jumping  = False
                    on_ground        = True
                    break
        if not on_ground and not gblocks and self.rect.bottom >= self.ground_y:
            self.rect.bottom = self.ground_y
            self.velocity_y  = 0.0
            if self.is_jumping:
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
            # Estilo Cartoon: Muy enérgico y sincronizado con velocidad física
            self.frame_index += (0.2 + abs(self.velocity_x) * 0.08)
            if self.frame_index >= len(self.frames_right):
                self.frame_index = 0
        else:
            self.frame_index = 0 
            # Eliminado balanceo del personaje por petición del usuario
            self._bob_offset = 0

        # Update variables de acción y disparo
        if self.velocity_x > 0: self.facing_right = True
        elif self.velocity_x < 0: self.facing_right = False
        
        if self.invulnerable_timer > 0:
            self.invulnerable_timer -= 1
            
        # FIX #3: p.update() eliminado de aquí — se ejecuta en el culling de main() en un solo ciclo

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

    def draw_with_bob(self, surface, camera_x):
        """Blitea el sprite con offset de bob y parpadeo. La resta de camera_x se hace aquí,
        aislando el modelo físico del cálculo visual. Nunca muta self.rect."""
        if self.invulnerable_timer > 0 and (self.invulnerable_timer // 4) % 2 == 0:
            return  # Parpadeo: no dibujar este frame
        # FIX #1: La resta visual se calcula aquí, self.rect.x jamás se toca
        draw_pos = (self.rect.x - camera_x, self.rect.y + self._bob_offset)
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
        # Ataque 30% más rápido: de 20 cuadros a 14 cuadros
        self.attack_timer = 14
        self.is_attacking = True
        offset = 20 if self.facing_right else -20
        proj_x = self.rect.centerx + offset
        self.projectiles.append(Projectile(proj_x, self.rect.centery - 25, self.facing_right, self.shot_count))
        self.shot_count += 1


# ==========================================
# 5. HUD — Panel Neón semi-transparente
# ==========================================
MAX_LIVES = 10

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


SAVE_FILE = "savegame.json"

def load_save():
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"player_name": ""}

def write_save(data: dict):
    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Save] Error guardando: {e}")


# ==========================================
# 7. MENÚ DE INICIO
# ==========================================
def show_start_menu(screen, clock, bg_surf):
    """Muestra el menú de inicio usando Fondo_Menu.png como fondo.
    Devuelve (player_name, action) donde action es 'play' o 'quit'.
    """
    save_data    = load_save()
    player_name  = save_data.get("player_name", "")
    input_active = True
    cursor_blink = 0

    try:
        f_sub   = pygame.font.SysFont("Consolas", 24, bold=True)
        f_btn   = pygame.font.SysFont("Consolas", 22, bold=True)
        f_input = pygame.font.SysFont("Consolas", 26)
        f_hint  = pygame.font.SysFont("Consolas", 16)
    except:
        f_sub = f_btn = f_input = f_hint = pygame.font.Font(None, 36)

    C_INPUT_BG   = (20, 12, 50, 180) # Semi-transparente
    C_INPUT_BORD = (140, 80, 255)
    C_INPUT_ACT  = (80, 255, 160)
    C_BTN_PLAY   = (60, 220, 150)
    C_BTN_QUIT   = (220, 80, 80)
    C_TEXT_MAIN  = (230, 210, 255)

    # RE-POSICIONAMIENTO Basado en el Fondo_Menu.png (que ya tiene el título)
    # El título termina aprox a los 320px
    input_r    = pygame.Rect(WIDTH // 2 - 200, 390, 400, 52)
    btn_play_r = pygame.Rect(WIDTH // 2 - 170, 480, 340, 58)
    btn_quit_r = pygame.Rect(WIDTH // 2 - 120, 560, 240, 48)

    while True:
        clock.tick(60)
        mouse_pos = pygame.mouse.get_pos()
        cursor_blink = (cursor_blink + 1) % 60

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                write_save({"player_name": player_name})
                return player_name, "quit"

            if event.type == pygame.MOUSEBUTTONDOWN:
                input_active = input_r.collidepoint(mouse_pos)
                if btn_play_r.collidepoint(mouse_pos) and player_name.strip():
                    write_save({"player_name": player_name.strip()})
                    return player_name.strip(), "play"
                if btn_quit_r.collidepoint(mouse_pos):
                    write_save({"player_name": player_name})
                    return player_name, "quit"

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN and player_name.strip():
                    write_save({"player_name": player_name.strip()})
                    return player_name.strip(), "play"
                elif event.key == pygame.K_BACKSPACE:
                    player_name = player_name[:-1]
                elif event.key == pygame.K_ESCAPE:
                    write_save({"player_name": player_name})
                    return player_name, "quit"
                elif len(player_name) < 20 and event.unicode.isprintable() and event.unicode.strip():
                    player_name += event.unicode

        # Fondo estático (ya tiene el título renderizado)
        screen.blit(bg_surf, (0, 0))

        # El overlay se ha eliminado para que se vea el fondo claro, 
        # o podemos usar uno muy tenue solo tras los controles
        
        # Label + campo de texto
        lbl = f_hint.render("Ingresa tu nombre de aventurero:", True, (50, 40, 100)) # Color oscuro para fondo claro
        # Sombrilla blanca para el texto para que se lea bien en cualquier parte
        lbl_shadow = f_hint.render("Ingresa tu nombre de aventurero:", True, (255, 255, 255))
        screen.blit(lbl_shadow, (WIDTH // 2 - lbl.get_width() // 2 + 1, 365))
        screen.blit(lbl, (WIDTH // 2 - lbl.get_width() // 2, 364))

        bord_col = C_INPUT_ACT if input_active else C_INPUT_BORD
        
        # Dibujo de caja de input con fondo oscuro traslúcido
        input_surf = pygame.Surface((input_r.width, input_r.height), pygame.SRCALPHA)
        pygame.draw.rect(input_surf, C_INPUT_BG, (0,0, input_r.width, input_r.height), border_radius=10)
        screen.blit(input_surf, (input_r.x, input_r.y))
        pygame.draw.rect(screen, bord_col, input_r, 2, border_radius=10)
        
        ns = f_input.render(player_name, True, (255, 255, 255))
        screen.blit(ns, (input_r.x + 14, input_r.y + 12))
        if input_active and cursor_blink < 30:
            pygame.draw.rect(screen, (200, 200, 255),
                             (input_r.x + 14 + ns.get_width() + 2, input_r.y + 10, 2, 30))

        # Botón JUGAR
        hov_p  = btn_play_r.collidepoint(mouse_pos)
        can_p  = bool(player_name.strip())
        btn_p_col = (0, 150, 90) if not hov_p else C_BTN_PLAY
        pygame.draw.rect(screen, btn_p_col, btn_play_r, border_radius=14)
        pygame.draw.rect(screen, C_BTN_PLAY, btn_play_r, 2, border_radius=14)
        play_lbl = f_btn.render("▶  INICIAR AVENTURA", True,
                                (255, 255, 255) if (hov_p and can_p) else ((200, 255, 220) if can_p else (100, 120, 100)))
        screen.blit(play_lbl, (btn_play_r.centerx - play_lbl.get_width()  // 2,
                                btn_play_r.centery - play_lbl.get_height() // 2))

        # Botón SALIR
        hov_q  = btn_quit_r.collidepoint(mouse_pos)
        btn_q_col = (140, 40, 40) if not hov_q else C_BTN_QUIT
        pygame.draw.rect(screen, btn_q_col, btn_quit_r, border_radius=12)
        pygame.draw.rect(screen, C_BTN_QUIT, btn_quit_r, 2, border_radius=12)
        quit_lbl = f_btn.render("✕  SALIR", True, (255, 200, 200) if hov_q else (200, 150, 150))
        screen.blit(quit_lbl, (btn_quit_r.centerx - quit_lbl.get_width()  // 2,
                                btn_quit_r.centery - quit_lbl.get_height() // 2))

        hint_txt = "Pulsa Enter para comenzar"
        hint = f_hint.render(hint_txt, True, (50, 40, 100))
        hint_s = f_hint.render(hint_txt, True, (255, 255, 255))
        screen.blit(hint_s, (WIDTH // 2 - hint.get_width() // 2 + 1, 621))
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 620))

        pygame.display.flip()

# ==========================================
# 7.5. MENU DE NIVELES
# ==========================================
def show_level_menu(screen, clock):
    try:
        bg = pygame.image.load("components/Fondo_Nivel1/Menu_Niveles.png").convert()
        bg = pygame.transform.scale(bg, (WIDTH, HEIGHT))
    except:
        bg = pygame.Surface((WIDTH, HEIGHT))
        bg.fill((20, 60, 100))
        
    rect_1 = pygame.Rect(280 - 60, 360 - 60, 120, 120)
    rect_2 = pygame.Rect(640 - 60, 360 - 60, 120, 120)
    rect_3 = pygame.Rect(1000 - 60, 360 - 60, 120, 120)
    
    try:
        f_info = pygame.font.SysFont("Consolas", 32, bold=True)
    except:
        f_info = pygame.font.Font(None, 40)
        
    while True:
        clock.tick(60)
        mouse_pos = pygame.mouse.get_pos()
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                write_save({"player_name": load_save().get("player_name", "")})
                return "quit"
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if rect_1.collidepoint(mouse_pos):
                    return "play_level_1"
                # Niveles 2 y 3 no hacen nada por ahora
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return "menu"

        screen.blit(bg, (0, 0))
        
        # Hover y feedback visual
        if rect_1.collidepoint(mouse_pos):
            pygame.draw.circle(screen, (255, 255, 255, 80), (280, 355), 70)
            lbl = f_info.render("Nivel 1: El Valle de Caramelo", True, (255, 255, 255))
            # Sombra
            lbl_s = f_info.render("Nivel 1: El Valle de Caramelo", True, (0, 0, 0))
            tx = WIDTH//2 - lbl.get_width()//2
            ty = HEIGHT - 100
            screen.blit(lbl_s, (tx+2, ty+2))
            screen.blit(lbl, (tx, ty))
        elif rect_2.collidepoint(mouse_pos):
            pygame.draw.circle(screen, (255, 255, 255, 80), (635, 365), 70)
            lbl = f_info.render("Nivel 2: Muy Pronto...", True, (200, 200, 200))
            lbl_s = f_info.render("Nivel 2: Muy Pronto...", True, (0, 0, 0))
            tx = WIDTH//2 - lbl.get_width()//2
            ty = HEIGHT - 100
            screen.blit(lbl_s, (tx+2, ty+2))
            screen.blit(lbl, (tx, ty))
        elif rect_3.collidepoint(mouse_pos):
            pygame.draw.circle(screen, (255, 255, 255, 80), (990, 360), 70)
            lbl = f_info.render("Nivel 3: Muy Pronto...", True, (200, 200, 200))
            lbl_s = f_info.render("Nivel 3: Muy Pronto...", True, (0, 0, 0))
            tx = WIDTH//2 - lbl.get_width()//2
            ty = HEIGHT - 100
            screen.blit(lbl_s, (tx+2, ty+2))
            screen.blit(lbl, (tx, ty))

        pygame.display.flip()


# ==========================================
# 8. GAME LOOP
# ==========================================
def main(player_name: str = "Jugador"):
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
        f_count = pygame.font.SysFont("Impact", 120)             
        f_btn   = pygame.font.SysFont("Consolas", 24, bold=True) 
        f_vic   = pygame.font.SysFont("Consolas", 40, bold=True) 
    except:
        font_sm = pygame.font.Font(None, 16)
        font_md = pygame.font.Font(None, 22)
        f_count = pygame.font.Font(None, 150)                    
        f_btn   = pygame.font.Font(None, 30)                     
        f_vic   = pygame.font.Font(None, 50)

    # ── Sonidos ──────────────────────────────────────────────────────────────
    try:
        sfx_game_over = pygame.mixer.Sound("components/Fondo_Nivel1/Sonido_Game_Over.mp3")
    except Exception as e:
        print(f"[Sonido] Fallo cargando Game Over SFX: {e}")
        sfx_game_over = None

    # ── GENERACIÓN DEL NUEVO FONDO Y BALCONES MUNDIALES ───────────────────────
    global PLATFORM_TEXTURES, TORRE_TEXTURES
    PLATFORM_TEXTURES = load_platform_textures(45)
    TORRE_TEXTURES = load_torre_textures()

    # ── CARGA DE FONDO PANORÁMICO MÓVIL (4 Imágenes Consecutivas) ──
    bg_tiled = []
    try:
        bg_dir = "components/Fondo_Nivel1"
        for i in range(1, 3): # Ahora solo usamos las 2 primeras imágenes
            path = os.path.join(bg_dir, f"Fondo ({i}).png")
            if os.path.exists(path):
                img = pygame.image.load(path).convert()
                # Escalamos cada parte del panorama al tamaño de pantalla
                bg_tiled.append(pygame.transform.scale(img, (WIDTH, HEIGHT)))
        
        if not bg_tiled: raise FileNotFoundError("No se hallaron los archivos Fondo (1)-(4)")
        total_bg_width = len(bg_tiled) * WIDTH
        print(f"[Fondo] Panorama de {len(bg_tiled)} imágenes cargado.")
    except Exception as e:
        print(f"[Fondo] Error cargando panorama: {e}. Fallback activo.")
        fallback = pygame.Surface((WIDTH, HEIGHT))
        fallback.fill((10, 5, 25))
        bg_tiled = [fallback]
        total_bg_width = WIDTH
        
    try:
        # Cargar Meta Dividida (Bandera + Castillo decorativo)
        target_h = 450 
        
        raw_bandera = pygame.image.load("components/Elementos_Espaciales1/Bandera_Meta.png").convert_alpha()
        b_aspect = raw_bandera.get_width() / raw_bandera.get_height()
        bandera_img = pygame.transform.scale(raw_bandera, (int(target_h * b_aspect), target_h))
        
        raw_castillo = pygame.image.load("components/Elementos_Espaciales1/Castillo_Meta.png").convert_alpha()
        c_aspect = raw_castillo.get_width() / raw_castillo.get_height()
        castillo_img = pygame.transform.scale(raw_castillo, (int(target_h * c_aspect), target_h))
    except Exception as e:
        print(f"[Meta] Fallaron sprites Meta divididos: {e}")
        bandera_img = pygame.Surface((100, 450))
        bandera_img.fill((0, 255, 0))
        castillo_img = pygame.Surface((300, 450))
        castillo_img.fill((255, 0, 0))

    rng = random.Random(101)
    
    # ── TORRES DECORATIVAS (5 en el mapa, c/u con balcón físico activo) ──
    # Definimos posiciones antes para que los balcones normales no se encimen
    TORRE_POSITIONS = [1800, 5200, 11000, 18500, 23000]

    # 1. Plataformas Universales (Balcones Físicos Object-Oriented)
    platforms = []
    pos_x = 240
    while pos_x < 24200:
        pw_gap = rng.randint(180, 400) # Hueco al siguiente
        
        # Filtro: No crear balcones normales cerca de las torres (Margen de 400px)
        near_tower = any(abs(pos_x - tp) < 400 for tp in TORRE_POSITIONS)
        if near_tower:
            pos_x += 300 # Saltamos la zona de la torre
            continue

        py = GROUND_Y - rng.randint(120, 450) # Elevaciones drásticas para ambiente espacial flotante
        texture_idx = rng.randint(0, 5) # Texturas 0-5 (balcones 1 a 6)
        
        # Generar plataforma inteligente
        new_plat = Platform(pos_x, py, texture_idx)
        platforms.append(new_plat)
        pos_x += new_plat.width + pw_gap
        
    platforms_x = [p.x for p in platforms] # Lista K-V para bisect rápido

    torres = []
    for i, tx in enumerate(TORRE_POSITIONS):
        # Pasar FLOOR_Y cuando esté disponible; lo guardamos en variable temporal
        # FLOOR_Y se calcula después del bloque de suelo, así que usamos GROUND_Y aqui
        # y actualizamos la y de la torre después si es necesario
        t = TorreBalcon(tx, i % 3)
        torres.append(t)
        platforms.append(t.platform)
    # Re-ordenar y re-indexar el array de plataformas con las torres incluidas
    platforms.sort(key=lambda p: p.x)
    platforms_x = [p.x for p in platforms]

    # ── CARGA Y LAYOUT DE SUELO (Usando únicamente Suelo.png original) ──
    _ground_rects = []   # pygame.Rect para colisiones (x, y, w, h)
    _ground_imgs  = []   # imagen correspondiente a cada rect
    try:
        path = os.path.join("components/Suelo_Nivel1", "Suelo.png")
        base_img = pygame.image.load(path).convert_alpha()
        
        # Layout: Colocar la imagen Suelo.png repetidamente con huecos
        GAP_WIDTH = 150   # px de vacío entre suelos
        LEVEL_TOTAL_WIDTH = 24000 # Largo estimado del nivel
        cur_x = 0
        
        bw, bh = base_img.get_width(), base_img.get_height()
        world_y = HEIGHT - bh # Pegado al fondo de la pantalla
        
        # Llenar el nivel con unidades de Suelo.png
        while cur_x < LEVEL_TOTAL_WIDTH:
            rect = pygame.Rect(cur_x, world_y, bw, bh)
            _ground_rects.append(rect)
            _ground_imgs.append(base_img)
            cur_x += bw + GAP_WIDTH

        # Precalcular xs para bisect (culling)
        ground_xs = [r.x for r in _ground_rects]
        print(f"[Suelo] {len(_ground_rects)} unidades de suelo cargadas, gap={GAP_WIDTH}px")
    except Exception as e:
        print(f"[Suelo] Error cargando Suelo.png: {e}. Fallback a suelo plano.")
        _ground_rects = [pygame.Rect(-1000, GROUND_Y, 40000, 100)]
        _ground_imgs  = []
        ground_xs     = [-1000]

    # Y de la superficie de suelo real (top del primer bloque + offset de la imagen)
    # 115px = 95 base + 20px extra pedidos por el usuario
    GROUND_OFFSET = 115
    FLOOR_Y = (_ground_rects[0].top + GROUND_OFFSET) if _ground_rects else GROUND_Y

    # Pre-calcular la lista de tops reales ordenada (para bisect O(log N) en Player)
    _ground_tops = sorted(r.top + GROUND_OFFSET for r in _ground_rects)

    # Re-anclar torres al FLOOR_Y real, enterrándolas más para que se vean detrás del suelo grueso
    for t in torres:
        t.y = FLOOR_Y - t.height + 120
        # Sincronizar plataforma de colisión con nueva altura visual
        t.platform.y = t.y
        # Vaciar imagen de plataforma para evitar render doble desfasado
        t.platform.image = pygame.Surface((0, 0), pygame.SRCALPHA)

    # 4. Peligros y Enemigos 
    LEVEL_END_X = 24000
    victory = False

    enemies = []

    # Spawn de Tiradoras Estáticas sobre los bloques de suelo (MÁXIMO 4)
    shooter_count = 0
    for grect in _ground_rects:
        if shooter_count >= 4:
            break
        if grect.x < 1500:
            continue
            
        fx = grect.x + 200
        while fx < grect.right - 150 and shooter_count < 4:
            enemies.append(ShooterFlower(fx, FLOOR_Y))
            shooter_count += 1
            fx += rng.randint(3500, 6000)

    # Spawn Dinámico de Voladoras y Caminantes
    # Empezar a los 2000px para dar margen al inicio
    ex = 2000
    while ex < LEVEL_END_X - 1000:
        # 1. Intentar Spawn de Gárgola (Pocas para el Nivel 1)
        is_clear = True
        for e in enemies:
            if abs(ex - e.rect.centerx) < 800: # Distancia de respiro amplia
                is_clear = False
                break
        
        if is_clear:
            flight_y = FLOOR_Y - rng.randint(180, 420)
            enemies.append(GargoyleEnemy(ex, flight_y))
        
        # Paso alargado para generar muchas menos gárgolas
        ex += rng.randint(1500, 3000)

        # 2. Intentar Spawn de Caminantes sobre plataformas (MÁS CAMINANTES)
        if rng.random() > 0.15: # 85% de probabilidad
            plat = rng.choice(platforms)
            if plat.x > 2000:
                is_clear_plat = True
                for e in enemies:
                    if abs(plat.centerx - e.rect.centerx) < 300:
                        is_clear_plat = False
                        break
                if is_clear_plat:
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

    # ── Cargando Recurso para Fin de Juego ──────────────────
    try:
        go_bg = pygame.image.load("components/Fondo_Nivel1/Game_Over.png").convert()
        go_bg = pygame.transform.scale(go_bg, (WIDTH, HEIGHT))
    except:
        go_bg = pygame.Surface((WIDTH, HEIGHT))
        go_bg.fill((150, 0, 0))
    btn_menu_niveles = pygame.Rect(WIDTH // 2 - 150, HEIGHT - 150, 300, 60)

    # Variables de Cámara
    camera_x = 0

    # ── Sprites ───────────────────────────────────────────────────────────────
    player = Player(FLOOR_Y, platforms)   # Spawn en la superficie real del suelo
    player._ground_blocks = _ground_rects
    player._ground_tops   = _ground_tops  # bisect list para colisión O(log N)

    # ── Cola y proceso de voz ─────────────────────────────────────────────────
    cmd_queue     = multiprocessing.Queue(maxsize=10)
    voice_process = VoiceController(cmd_queue, settings)
    voice_process.start()

    # ── Estado HUD ────────────────────────────────────────────────────────────
    last_command  = "ESPERANDO VOZ..."
    cmd_color     = C_CMD_IDLE
    last_cmd_time = 0.0
    lives         = MAX_LIVES
    paused        = False

    # ── Máquina de Estados ──
    game_state  = "STARTING" # STARTING, PLAYING, GAMEOVER
    state_timer = pygame.time.get_ticks()

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN ENGINE LOOP
    # ─────────────────────────────────────────────────────────────────────────
    running = True
    while running:
        # ── Eventos ──────────────────────────────────────────────────────────
        mouse_clicked = False
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                if event.key == pygame.K_SPACE:
                    paused = not paused
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_clicked = True

        # ── SISTEMA DE CÁMARA (SCROLLING LINEAL) ──────────────────────────────
        camera_x = max(0, player.rect.x - (WIDTH // 2 - 100))

        # ── FRUSTUM CULLING (Cálculo de Plataformas y Suelo Visibles) ─────────
        # Buscar el punto de inicio en el array ordenado
        idx_start_plat = bisect.bisect_left(platforms_x, camera_x - 1000)
        idx_end_plat   = bisect.bisect_right(platforms_x, camera_x + WIDTH)
        visible_platforms = platforms[max(0, idx_start_plat):idx_end_plat]

        if game_state == "PLAYING" and not paused:
            # ── Consumo de cola en ráfaga ─────────────────────────────
            active_tokens = set()
            while not cmd_queue.empty():
                try:
                    raw = cmd_queue.get_nowait().lower().strip(".,!? ¡¿")
                    active_tokens.update(raw.split())
                    last_command = f"  {raw.upper()}"
                    cmd_color = C_CMD_ACTIVE
                    last_cmd_time = time.time()
                except multiprocessing.queues.Empty:
                    break
            
            if active_tokens & ATTACK_SET: player.attack()
            if active_tokens & JUMP_SET: player.queue_jump()
            
            if active_tokens & STOP_SET: player.stop()
            elif active_tokens & RUN_SET: player.run()

            # ── Fade del color del comando tras el debounce ───────────────────────
            if time.time() - last_cmd_time > DEBOUNCE_SECS:
                cmd_color = C_CMD_IDLE

            # ── Culling Enemy Projectiles (Filtrado O(N) en una pasada C) ─────────
            surviving_ep = []
            for ep in enemy_projectiles:
                ep.update()
                hit_plat = ep.rect.collidelist(visible_platforms) != -1
                out_of_bounds = ep.rect.x < camera_x - 100 or ep.rect.x > camera_x + WIDTH + 100
                hit_player = ep.rect.colliderect(player.rect)
                
                if hit_player:
                    if player.take_damage(): lives -= 1
                
                if not (hit_plat or out_of_bounds or hit_player):
                    surviving_ep.append(ep)
            enemy_projectiles = surviving_ep
            
            # ── INTERACCIONES Y LÓGICA (Solo si no hemos ganado) ──────────────────
            if player.rect.centerx >= LEVEL_END_X and not victory:
                victory = True
                player.stop()

            if not victory:
                surviving_enemies = []
                # Evaluador de daño O(1) cruzado
                player_proj_rects = [p.rect for p in player.projectiles]
                
                for e in enemies:
                    if camera_x - 200 < e.rect.x < camera_x + WIDTH + 200:
                        # Extraer malla de terreno local para sus lógicas físicas y límites
                        visible_ground = [g for g in _ground_rects if e.rect.x - 300 < g.x < e.rect.x + 300]
                        e.update(visible_platforms=visible_platforms, player_x=player.rect.centerx, enemy_projectiles=enemy_projectiles, visible_ground=visible_ground, ground_offset=GROUND_OFFSET)
                        
                        if e.rect.colliderect(player.rect) and player.take_damage():
                            lives -= 1
                            
                        # Detección de impacto rápido (C-Level Array)
                        hit_by_proj_idx = e.rect.collidelist(player_proj_rects)
                        if hit_by_proj_idx != -1:
                            # Marcar el proyectil del jugador para eliminación y destruir enemigo
                            player.projectiles[hit_by_proj_idx].to_kill = True
                            continue # El enemigo muere, no entra a surviving_enemies
                            
                    # Culling de IA que cayó en abismos (Memoria O(1) segura)
                    if getattr(e, 'to_kill', False) or e.rect.top > HEIGHT + 400:
                        continue
                        
                    surviving_enemies.append(e)
                enemies = surviving_enemies

                # FIX #3: p.update() ahora vive aquí — un único ciclo de iteración
                surviving_player_proj = []
                for p in player.projectiles:
                    p.update()
                    if getattr(p, 'to_kill', False): continue
                    
                    dist_traveled = abs(p.rect.x - getattr(p, 'start_x', p.rect.x))
                    # El proyectil no desaparece al tocar plataformas para que sirva en movimiento
                    out_of_bounds = p.rect.x < camera_x - 300 or p.rect.x > camera_x + WIDTH + 300
                    
                    if out_of_bounds and dist_traveled >= 800:
                        continue
                        
                    surviving_player_proj.append(p)
                player.projectiles = surviving_player_proj
                
                # Update físico principal del jugador
                player.update(visible_platforms)

                # Muerte por caída al vacío (Game Over Automático)
                if player.rect.top > HEIGHT + 50 and player.invulnerable_timer == 0:
                    lives = 0

                if lives <= 0:
                    # Cambio a estado GAMEOVER
                    if game_state != "GAMEOVER" and sfx_game_over:
                        pygame.mixer.Sound.play(sfx_game_over)
                    game_state = "GAMEOVER"
                    state_timer = pygame.time.get_ticks()
        
        elif game_state == "STARTING":
            if pygame.time.get_ticks() - state_timer > 3000:
                game_state = "PLAYING"
                # Vaciado fuerte (Ignora el .empty() que falla en Windows)
                for _ in range(5):
                    try:
                        cmd_queue.get_nowait()
                    except:
                        break
                
        elif game_state == "GAMEOVER":
            if mouse_clicked and btn_menu_niveles.collidepoint(pygame.mouse.get_pos()):
                return "MENU_NIVELES"

        # ── RENDERIZADO DE FONDO PANORÁMICO INFINITO (Optimizado) ──
        parallax_x = (camera_x * 0.15) % total_bg_width
        
        for i in range(len(bg_tiled)):
            x_pos = (i * WIDTH) - parallax_x
            
            # Solo dibujar si la imagen roza la pantalla
            if -WIDTH < x_pos < WIDTH:
                screen.blit(bg_tiled[i], (x_pos, 0))
            
            # Wrap-around (Imagen repetida conectando el final)
            x_pos_wrap = x_pos + total_bg_width
            if -WIDTH < x_pos_wrap < WIDTH:
                screen.blit(bg_tiled[i], (x_pos_wrap, 0))

        # 2. Torres Decorativas (AHORA DETRÁS DEL SUELO)
        for t in torres:
            tx_screen = t.x - camera_x
            if -t.width < tx_screen < WIDTH + t.width:
                screen.blit(t.img, (tx_screen, t.y))

        # 3. SUELO: Bloques anchos con gaps entre ellos
        for idx, grect in enumerate(_ground_rects):
            sx = grect.x - camera_x
            if sx + grect.width < -50 or sx > WIDTH + 50:
                continue
            if idx < len(_ground_imgs):
                screen.blit(_ground_imgs[idx], (sx, grect.y))
        
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
        # 8. Meta Compuesta (Bandera Izquierda + Castillo Decorativo a la Derecha)
        bandera_x = LEVEL_END_X - 100 # Se alinea perfecta con el overlap de cruzarla
        screen.blit(bandera_img, (bandera_x - camera_x, GROUND_Y - bandera_img.get_height() + 70))
        # Castillo justo al lado, viéndose completo
        screen.blit(castillo_img, (bandera_x + bandera_img.get_width() - 20 - camera_x, GROUND_Y - castillo_img.get_height() + 70))

        # FIX #1: draw_with_bob recibe camera_x y realiza la resta visual internamente
        player.draw_with_bob(screen, camera_x)

        # Capa UI: Cartel Victoria
        if victory:
            # Box central
            vw, vh = 500, 100
            vx, vy = WIDTH // 2 - vw // 2, HEIGHT // 3
            pygame.draw.rect(screen, (30, 25, 40, 200), (vx, vy, vw, vh), border_radius=15)
            pygame.draw.rect(screen, (255, 215, 0), (vx, vy, vw, vh), 3, border_radius=15)
            # Text
            lbl_vic = f_vic.render("NIVEL COMPLETADO", True, (255, 215, 0))
            screen.blit(lbl_vic, (WIDTH // 2 - lbl_vic.get_width() // 2, vy + vh // 2 - lbl_vic.get_height() // 2))

        # Capa UI: Cartel Pausa
        if paused:
            screen.blit(pause_overlay, (0, 0))

        # HUD dinámico (solo texto blit o render si cambia el caché)
        draw_hud(screen, hud_bg, font_sm, font_md,
                 last_command, cmd_color, last_cmd_time, DEBOUNCE_SECS, lives, hud_cache)

        # ── OVERLAYS DE ESTADO ────────────────────────────────────────────────
        if game_state == "STARTING":
            # Conteo de 3 segundos
            secs = str(math.ceil((3000 - (pygame.time.get_ticks() - state_timer)) / 1000))
            
            # Sombra
            txt_s = f_count.render(secs, True, (20, 10, 40))
            screen.blit(txt_s, (WIDTH // 2 - txt_s.get_width() // 2 + 5, HEIGHT // 2 - txt_s.get_height() // 2 + 5))
            # Texto principal
            txt = f_count.render(secs, True, (255, 255, 255))
            screen.blit(txt, (WIDTH // 2 - txt.get_width() // 2, HEIGHT // 2 - txt.get_height() // 2))

        elif game_state == "GAMEOVER":
            # Usando Game_Over.png de fondo
            screen.blit(go_bg, (0, 0))
            
            # Botón Volver al Menú de Niveles
            mouse_pos = pygame.mouse.get_pos()
            hov = btn_menu_niveles.collidepoint(mouse_pos)
            pygame.draw.rect(screen, (0, 150, 90) if not hov else (60, 220, 150), btn_menu_niveles, border_radius=15)
            pygame.draw.rect(screen, (255, 255, 255), btn_menu_niveles, 2, border_radius=15)
            
            txt = f_btn.render("VOLVER A NIVELES", True, (255, 255, 255))
            screen.blit(txt, (btn_menu_niveles.centerx - txt.get_width()//2, btn_menu_niveles.centery - txt.get_height()//2))

        pygame.display.flip()
        clock.tick(FPS)

    print("[Pygame] Apagando el juego...")
    voice_process.terminate()
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    # Inicialización única de pygame y recursos compartidos del menú
    pygame.init()
    pygame.font.init()
    _screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Voice-Quest  ★  Star Candy Adventures")
    _clock  = pygame.time.Clock()

    # Cargar fondo para el menú (antes de lanzar main)
    _bg_menu = None
    try:
        _path_menu = os.path.join("components/Fondo_Nivel1", "Fondo_Menu.png")
        if os.path.exists(_path_menu):
            _img = pygame.image.load(_path_menu).convert()
            _bg_menu = pygame.transform.scale(_img, (WIDTH, HEIGHT))
        else:
            _bg_menu = pygame.Surface((WIDTH, HEIGHT))
            _bg_menu.fill((10, 5, 25))
    except Exception as e:
        print(f"[Menu] Error cargando Fondo_Menu.png: {e}")
        _bg_menu = pygame.Surface((WIDTH, HEIGHT))
        _bg_menu.fill((10, 5, 25))

    while True:
        name, action = show_start_menu(_screen, _clock, _bg_menu)
        if action == "quit":
            break
            
        # Entramos al ciclo del Menú de Niveles
        while True:
            lvl_action = show_level_menu(_screen, _clock)
            if lvl_action == "quit":
                pygame.quit()
                sys.exit()
            elif lvl_action == "menu":
                break # Regresa al Menú Principal (show_start_menu)
            elif lvl_action == "play_level_1":
                result = main(player_name=name)
                # Si el jugador pierde o gana y regresa:
                if result == "MENU":
                    break # Regresa a pantalla de inicio
                # Si result es "MENU_NIVELES", continuamos en el while interno

    pygame.quit()
    sys.exit()
