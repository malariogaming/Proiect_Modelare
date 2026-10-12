from ursina import *
import random
import math

app = Ursina()

# --- PROIECTILE ---
class Projectile(Entity):
    def __init__(self, position, target, damage, **kwargs):
        super().__init__(model='cube', scale=(0.05, 0.05, 0.6), color=color.black, position=position, **kwargs)
        self.target = target
        self.damage = damage
        self.speed = 15
        if self.target: self.look_at(self.target)
            
    def update(self):
        if not self.target or self.target.hp <= 0:
            destroy(self)
            return
            
        direction = (self.target.position - self.position).normalized()
        self.position += direction * self.speed * time.dt
        self.look_at(self.target)
        
        if distance(self, self.target) < 1:
            knockback_dir = direction
            knockback_dir.y = 0
            self.target.position += knockback_dir * 0.4
            self.target.take_damage(self.damage)
            destroy(self)

# --- CLASA DE BAZĂ (OMULEȚUL) ---
class Unit(Entity):
    def __init__(self, position, team, hp, speed, attack_range, attack_damage, attack_cooldown, **kwargs):
        # Baza devine invizibilă, o folosim doar pentru coliziuni și logică
        super().__init__(
            model='cube',
            color=color.rgba(0,0,0,0), 
            position=position,
            collider='box',
            **kwargs
        )
        self.team = team
        self.team_color = color.red if team == 'red' else color.blue
        self.hp = hp
        self.speed = speed
        self.attack_range = attack_range
        self.attack_damage = attack_damage
        self.attack_cooldown = attack_cooldown
        self.attack_timer = 0
        self.is_dead = False
        self.radius = 0.5 
        
        self.anim_time = random.uniform(0, 10) # Fiecare unitate mișcă mâinile decalat
        self.build_humanoid()

    def build_humanoid(self):
        # Asamblăm omulețul!
        self.body = Entity(parent=self, y=0.1)
        
        # Capul
        self.head = Entity(parent=self.body, model='sphere', color=self.team_color, scale=0.5, y=1.2)
        # Trunchiul
        self.torso = Entity(parent=self.body, model='cube', color=self.team_color, scale=(0.5, 0.6, 0.3), y=0.6)
        
        # Mâinile (origin=(0, 0.5, 0) mută "balamaua" sus la umăr)
        self.arm_l = Entity(parent=self.body, model='cube', color=self.team_color, scale=(0.15, 0.5, 0.15), position=(-0.35, 0.8, 0), origin=(0, 0.5, 0))
        self.arm_r = Entity(parent=self.body, model='cube', color=self.team_color, scale=(0.15, 0.5, 0.15), position=(0.35, 0.8, 0), origin=(0, 0.5, 0))
        
        # Picioarele (balamaua sus la șold)
        self.leg_l = Entity(parent=self.body, model='cube', color=self.team_color, scale=(0.15, 0.6, 0.15), position=(-0.15, 0.3, 0), origin=(0, 0.5, 0))
        self.leg_r = Entity(parent=self.body, model='cube', color=self.team_color, scale=(0.15, 0.6, 0.15), position=(0.15, 0.3, 0), origin=(0, 0.5, 0))

    def update(self):
        if not manager.is_battling or self.is_dead or manager.game_over:
            return

        # 1. Soft Collision
        for other in scene.entities:
            if isinstance(other, Unit) and other != self and not other.is_dead:
                dist = distance(self, other)
                min_dist = self.radius + other.radius
                if 0 < dist < min_dist:
                    push_dir = (self.position - other.position).normalized()
                    push_dir.y = 0 
                    self.position += push_dir * (min_dist - dist) * 4 * time.dt

        # 2. Logică și Animații
        enemies = [e for e in scene.entities if isinstance(e, Unit) and e.team != self.team and not e.is_dead]
        if not enemies: return

        closest_enemy = min(enemies, key=lambda e: distance(self, e))
        dist = distance(self, closest_enemy)

        if dist > self.attack_range:
            # Mișcare către inamic
            direction = (closest_enemy.position - self.position).normalized()
            direction.y = 0 
            self.position += direction * self.speed * time.dt
            self.look_at(closest_enemy)
            self.rotation_x = 0 
            
            # Animația de Alergare (Mișcăm brațele și picioarele cu funcții Sinus)
            self.anim_time += time.dt * self.speed * 4
            if hasattr(self, 'is_cavalry'):
                self.leg_fl.rotation_x = math.sin(self.anim_time) * 30
                self.leg_br.rotation_x = math.sin(self.anim_time) * 30
                self.leg_fr.rotation_x = math.cos(self.anim_time) * 30
                self.leg_bl.rotation_x = math.cos(self.anim_time) * 30
            else:
                self.leg_l.rotation_x = math.sin(self.anim_time) * 45
                self.leg_r.rotation_x = math.cos(self.anim_time) * 45
                self.arm_l.rotation_x = math.cos(self.anim_time) * 45
                self.arm_r.rotation_x = math.sin(self.anim_time) * 45
        else:
            # Idle (Ne oprim din mers)
            if hasattr(self, 'is_cavalry'):
                self.leg_fl.rotation_x = 0; self.leg_br.rotation_x = 0
                self.leg_fr.rotation_x = 0; self.leg_bl.rotation_x = 0
            else:
                self.leg_l.rotation_x = 0
                self.leg_r.rotation_x = 0

            # Atac
            self.attack_timer += time.dt
            if self.attack_timer >= self.attack_cooldown:
                self.perform_attack(closest_enemy)
                self.attack_timer = 0
                
    def perform_attack(self, target):
        target.take_damage(self.attack_damage)
        
        if hasattr(self, 'arm_r'):
            self.arm_r.rotation_x = -100 
            self.arm_r.animate_rotation_x(0, duration=0.3) 
            
            # Dacă lovește cu sabia (și nu e arcaș), redăm sunetul
            Audio('sabie.wav', autoplay=True)

        knockback_dir = (target.position - self.position).normalized()
        knockback_dir.y = 0
        target.position += knockback_dir * 0.3

    def take_damage(self, amount):
        if self.is_dead: return
        self.hp -= amount
        # Facem capul să clipească alb
        if hasattr(self, 'head'): self.head.blink(color.white, duration=0.1)
        if self.hp <= 0: self.die()

    def die(self):
        self.is_dead = True
        
        # Facem corpul gri la moarte
        for child in self.body.children:
            child.color = color.gray
        
        # Yeet effect
        jump_target = self.position + Vec3(random.uniform(-4, 4), random.uniform(3, 7), random.uniform(-4, 4))
        spin_target = Vec3(random.randint(360, 1080), random.randint(360, 1080), random.randint(360, 1080))
        
        self.animate_position(jump_target, duration=0.8, curve=curve.out_expo)
        self.body.animate_rotation(spin_target, duration=0.8) # Învârtim tot corpul vizual
        
        destroy(self, delay=1.5)


# --- CLASELE SPECIFICE (Aspect și Arme) ---

class Knight(Unit):
    def __init__(self, position, team):
        super().__init__(position, team, hp=120, speed=3, attack_range=1.5, attack_damage=30, attack_cooldown=1.0)
        # Decorăm omulețul existent
        Entity(parent=self.head, model='cube', color=color.dark_gray, scale=(1.1, 0.4, 1.1), position=(0, 0.2, 0)) # Cască
        Entity(parent=self.arm_r, model='cube', color=color.light_gray, scale=(0.5, 1.5, 1.0), position=(0, -0.6, 0.5)) # Sabie

class Archer(Unit):
    def __init__(self, position, team):
        super().__init__(position, team, hp=60, speed=2, attack_range=12, attack_damage=15, attack_cooldown=1.5)
        # Ochelari și Arc
        Entity(parent=self.head, model='cube', color=color.black, scale=(0.9, 0.3, 0.3), position=(0, 0.1, 0.4)) 
        Entity(parent=self.arm_l, model='cube', color=color.brown, scale=(0.5, 2.0, 0.5), position=(0, -0.4, 0.5)) 

    def perform_attack(self, target):
        Projectile(position=self.position + Vec3(0, 1.2, 0), target=target, damage=self.attack_damage)
        Audio('sageata.wav', autoplay=True) # Redă sunetul când trage

class Cavalry(Unit):
    def __init__(self, position, team):
        super().__init__(position, team, hp=200, speed=7, attack_range=2.5, attack_damage=45, attack_cooldown=1.2)
        self.radius = 1.0

    def build_humanoid(self):
        # Suprascriem corpul umanoid cu un CAL + CĂLĂREȚ
        self.is_cavalry = True
        self.body = Entity(parent=self, y=0)
        
        # Calul
        self.horse_body = Entity(parent=self.body, model='cube', color=color.rgb(139, 69, 19), scale=(0.8, 0.7, 1.6), y=0.7)
        self.horse_head = Entity(parent=self.horse_body, model='cube', color=color.rgb(120, 50, 10), scale=(0.4, 0.6, 0.4), position=(0, 0.5, 0.6))
        
        # Picioarele Calului
        self.leg_fl = Entity(parent=self.body, model='cube', color=color.rgb(120, 50, 10), scale=(0.15, 0.6, 0.15), position=(-0.3, 0.3, 0.6), origin=(0, 0.5, 0))
        self.leg_fr = Entity(parent=self.body, model='cube', color=color.rgb(120, 50, 10), scale=(0.15, 0.6, 0.15), position=(0.3, 0.3, 0.6), origin=(0, 0.5, 0))
        self.leg_bl = Entity(parent=self.body, model='cube', color=color.rgb(120, 50, 10), scale=(0.15, 0.6, 0.15), position=(-0.3, 0.3, -0.6), origin=(0, 0.5, 0))
        self.leg_br = Entity(parent=self.body, model='cube', color=color.rgb(120, 50, 10), scale=(0.15, 0.6, 0.15), position=(0.3, 0.3, -0.6), origin=(0, 0.5, 0))

        # Călărețul de deasupra
        self.rider = Entity(parent=self.body, y=1.2, z=-0.2)
        Entity(parent=self.rider, model='sphere', color=self.team_color, scale=0.4, y=0.5) 
        Entity(parent=self.rider, model='cube', color=self.team_color, scale=(0.4, 0.5, 0.3), y=0.1) 
        Entity(parent=self.rider, model='cube', color=color.light_gray, scale=(0.05, 0.05, 2.5), position=(0.4, 0.2, 1.0)) # Sulița


# --- MANAGERUL JOCULUI ---
class BattleManager(Entity):
    def __init__(self):
        super().__init__()
        self.is_battling = False
        self.game_over = False
        self.current_team = 'red'
        self.selected_class = 'knight'
        
        self.ui_status = Text(text="", origin=(0, 0), y=0.45)
        self.ui_controls = Text(text="1: Cavaler | 2: Arcas | 3: Cavalerie || T: Echipa || SPACE: Start", origin=(0, 0), y=0.40, scale=0.8)
        self.ui_victory = Text(text="", origin=(0, 0), y=0.1, scale=3)
        self.update_ui()

        self.ground = Entity(model='plane', scale=(40, 1, 40), color=color.green.tint(-0.2), collider='box')

    def update(self):
        if not self.is_battling or self.game_over: return

        red_alive = sum(1 for e in scene.entities if isinstance(e, Unit) and e.team == 'red' and not e.is_dead)
        blue_alive = sum(1 for e in scene.entities if isinstance(e, Unit) and e.team == 'blue' and not e.is_dead)

        if red_alive == 0 and blue_alive > 0: self.declare_winner("ALBASTRA", color.blue)
        elif blue_alive == 0 and red_alive > 0: self.declare_winner("ROSIE", color.red)
        elif red_alive == 0 and blue_alive == 0: self.declare_winner("EGALITATE", color.gray)

    def declare_winner(self, winner_name, win_color):
        self.game_over = True
        self.ui_victory.text = f"ECHIPA {winner_name} A CASTIGAT!\nApasa 'R' pentru Restart"
        self.ui_victory.color = win_color
        self.ui_status.text = "Lupta s-a incheiat."

    def update_ui(self):
        if not self.is_battling:
            self.ui_status.text = f"Selectat: {self.selected_class.upper()} | Echipa: {self.current_team.upper()}"
        else:
            self.ui_status.text = "LUPTA A INCEPUT!"
            self.ui_controls.enabled = False

    def input(self, key):
        if key == 'r' and self.game_over:
            for e in scene.entities:
                if isinstance(e, (Unit, Projectile)): destroy(e)
            self.is_battling = False
            self.game_over = False
            self.ui_victory.text = ""
            self.ui_controls.enabled = True
            self.update_ui()
            return

        if self.is_battling: return 
        if key == 'space':
            self.is_battling = True
            self.update_ui()
            
            if not hasattr(self, 'bg_music'):
                self.bg_music = Audio('muzica.mp3', loop=True, autoplay=True)
            else:
                self.bg_music.resume()
            
        if key == '1': self.selected_class = 'knight'
        if key == '2': self.selected_class = 'archer'
        if key == '3': self.selected_class = 'cavalry'
        if key == 't': self.current_team = 'blue' if self.current_team == 'red' else 'red'
        self.update_ui()

        if key == 'left mouse down' and mouse.hovered_entity == self.ground:
            pos = mouse.world_point
            if pos:
                if self.selected_class == 'knight': Knight(position=(pos.x, 0.1, pos.z), team=self.current_team)
                elif self.selected_class == 'archer': Archer(position=(pos.x, 0.1, pos.z), team=self.current_team)
                elif self.selected_class == 'cavalry': Cavalry(position=(pos.x, 0.1, pos.z), team=self.current_team)

manager = BattleManager()
camera_controller = EditorCamera() 
app.run()