import collections
import mathutils
from . import Pack


def all_subclasses(cls):
    return cls.__subclasses__() + [g for s in cls.__subclasses__()
                                    for g in all_subclasses(s)]


class ServerComponentSystem:

    def __init__(self, game):
        self.game = game
        self.owner = game.owner

        self.hostmode = 'server'

        # List of components ordered by ID (16 bit unsigned short)
        self.active_components_ = [None] * 65535
        # Next component ID to use
        self.next_active_id_ = 0
        # List of freed component IDs ordered oldest-newest
        self.freed_active_id_ = collections.deque()

        # Indexes possible components by a user-defined value
        self.component_dict = {}
        # Indexes possible components by a generated ID for fast lookups
        self.component_list = []
        self.next_component_index_ = 0

        self.registerComponent(MainComponent)
        self.createMainComponent()

        component_subs = all_subclasses(Component)
        for cls in component_subs:
            self.registerComponent(cls)

    def createMainComponent(self):
        net_id = self.getNewID()  # Should be 0 every time
        self.MainComponent = MainComponent(self, 0)
        self.active_components_[net_id] = self.MainComponent

        if net_id != 0:
            print ("ERROR - base component ID is not 0")

    def registerComponent(self, comp):
        comp_name = comp.__name__
        # One-time per component type, both client and server
        comp.comp_index = self.next_component_index_
        self.component_dict[comp_name] = self.next_component_index_
        self.component_list.append(comp)
        self.next_component_index_ += 1

    def getNewID(self):
        if len(self.freed_active_id_):
            return self.freed_active_id_.popleft()
        elif self.next_active_id_ <= 65535:
            cid = self.next_active_id_
            self.next_active_id_ += 1
            return cid
        else:
            return None

    """
    def spawnComponentByIndex(self, comp_index, pos, ori):
        net_id = self.getNewID()
        if net_id is not None:
            comp = self.component_list[comp_index](self,
                net_id, comp_index, pos, ori)
            self.active_components_[net_id] = comp

            ####### How should the client handle components?
            # comp_index, net_id
            # posx, posy, posz
            # rotx, roty, rotz

            self.MainComponent.packer.pack('addComponent',
                    [net_id, comp_index,
                    pos[0], pos[1], pos[2],
                    ori[0], ori[1], ori[2],
                    comp.getInputState()])

            return comp
        else:
            print ("Component limit reached")
            return None

    def spawnComponent(self, comp_name, pos, ori):
        # Spawns a component in the world by the user-defined index
        # Wraps spawnComponentByIndex
        comp_index = self.component_dict[comp_name]
        return self.spawnComponentByIndex(comp_index, pos, ori)
    """

    def spawnComponent(self, comp_index):

        if type(comp_index is str):
            comp_index = self.getComponentIndex(comp_index)

        net_id = self.getNewID()
        if net_id is not None:
            comp = self.component_list[comp_index](self, net_id)
            self.active_components_[net_id] = comp

            ###### The data
            # comp_index, net_id,
            # posx, posy, posz,
            # rotx, roty, rotz,
            # inputstate

            self.MainComponent.packer.pack('addComponent',
                (net_id, comp_index))

            return comp

        else:
            print ("Component limit reached")
            return None

    def getComponentIndex(self, comp_name):
        return self.component_dict[comp_name]

    def freeComponent(self, comp):
        # Send backlogged data before freeing
        self.game.systems['Server'].sendQueuedData()

        net_id = comp.net_id
        self.active_components_[net_id] = None
        self.freed_active_id_.append(net_id)

    def getComponent(self, net_id):
        return self.active_components_[net_id]

    def getQueuedData(self):
        bdata_list = []

        i = 0
        for c in self.active_components_:
            if i == self.next_active_id_:
                # No point iterating over unused component slots
                break

            if c is not None:
                bdata_list.append(c.packer.queued_data)
                c.packer.queued_data = []

            i += 1

        return bdata_list

    def getGameState(self, client_id):
        bdata_list = []

        key = 'addComponent'
        packer = self.MainComponent.packer
        main_id = self.MainComponent.net_id
        p_id = packer.pack_index[key]
        dataprocessor = packer.pack_list[p_id]

        i = 0
        for c in self.active_components_:
            if i == self.next_active_id_:
                # No point iterating over unused component slots
                break

            if i == 0:
                net_id = c.net_id
                comp_index = c.comp_index
                data = [client_id]

                c_p_id = packer.pack_index['setClientID']
                c_dataprocessor = packer.pack_list[c_p_id]
                bdata_list.append(
                    c_dataprocessor.getBytes(main_id, c_p_id, data))

            elif c is not None:
                net_id = c.net_id
                comp_index = c.comp_index

                #if c.ob_ is not None:
                #    pos = c.ob_.worldPosition
                #    rot = c.ob_.worldOrientation.to_euler()
                #else:
                #    pos = [0.0, 0.0, 0.0]
                #    rot = [0.0, 0.0, 0.0]

                #data = [net_id, comp_index,
                #    pos[0], pos[1], pos[2],
                #    rot[0], rot[1], rot[2],
                #    c.getInputState()]

                data = [net_id, comp_index]

                bdata_list.append(
                    dataprocessor.getBytes(main_id, p_id, data))

                ## Need to send state before continuing
                statedata = c.c_getStateData()
                if statedata is not None:
                    bdata_list.append(statedata)

            i += 1

        return bdata_list

    def update(self, dt):
        i = 0
        for c in self.active_components_:
            if i == self.next_active_id_:
                # No point iterating over unused component slots
                break

            if c is not None:
                c.c_update(dt)
                c.c_server_update(dt)

            i += 1


class ClientComponentSystem(ServerComponentSystem):

    def __init__(self, game):
        ServerComponentSystem.__init__(self, game)
        self.hostmode = 'client'
        self.client_id = -1

    def spawnComponentByIndex(self, net_id, comp_index):
        comp = self.component_list[comp_index](self,
            net_id)
        self.active_components_[net_id] = comp

        if net_id > self.next_active_id_:
            self.next_active_id_ = net_id

        return comp

    def spawnComponent(self, comp_name):
        print ("WARNING - spawnComponent not implemented on client")

    def freeComponent(self, comp):
        net_id = comp.net_id
        self.active_components_[net_id] = None

    def update(self, dt):
        i = 0
        for c in self.active_components_:
            if i == self.next_active_id_:
                # No point iterating over unused component slots
                break

            if c is not None:
                c.c_update(dt)

            i += 1


class Component:

    def __init__(self, mgr, net_id):
        self.mgr = mgr
        self.ob_ = None
        self.net_id = net_id

        # List of clients (by ID) with permission to set input
        self.client_permission_list_ = []

        # Replaces the funky input status dict with a bitmask list
        self.input_mask = [0] * 32

        # Indexes input keys by a user-defined value
        self.input_dict = {}

        # Consumed as inputs are registered, valid < 32
        self.next_input_index_ = 0

        # Current input state
        #self.input_state = {}

        # Predicted input state for clients with input permission
        # For now it's only for requesting changes
        #self.predicted_input_state = {}

        # Next input index (32 bit signed int)
        #self.next_input_index_ = 1
        # 1 must always be part of the state for the compression to work,
        # As such 1 is reserved.
        #self.next_input_index_ = 2

        # True when the input state has changed in a frame
        # Used to queue network updates
        self.input_changed_ = False

        # Data packer for network play
        self.packer = Pack.Packer(self)

        # Register the input permission packer
        self.packer.registerPack('permission_', self.process_permission_,
            [Pack.INT, Pack.INT])

        # Register the input update packer
        self.packer.registerPack('input_', self.process_input_,
            [Pack.INT])

        self.c_register_setup()

    def registerInput(self, input_name):
        # Run once per input key at component init
        # The idea is that we can compress the state
        #     of ~30 predefined keys into a single integer
        """
        if self.next_input_index_ < 2147483647:
            self.input_dict[input_name] = self.next_input_index_
            self.input_state[input_name] = False
            self.predicted_input_state[input_name] = False
            self.next_input_index_ *= 2
            return True
        else:
            print ("Input limit reached")
            return False
        """
        if self.next_input_index_ < 32:
            index = self.next_input_index_
            self.input_dict[input_name] = index
            self.input_mask[index] = 0

            self.next_input_index_ += 1
            return True
        else:
            print ("Input limit reached")
            return False

    def assignClientInput(self, input_name, input_index):
        # The client version of registerInput
        self.input_dict[input_name] = input_index
        self.input_state[input_name] = False

    def setInput(self, input_name, state):
        # Called when keys are pressed
        """
        if self.mgr.hostmode == 'server':
            if self.input_state[input_name] != state:
                self.input_state[input_name] = state
                self.input_changed_ = True

        else:
            if self.predicted_input_state[input_name] != state:
                self.predicted_input_state[input_name] = state
                self.input_changed_ = True
        """
        if state:
            state = 1
        else:
            state = 0

        index = self.input_dict[input_name]
        if self.input_mask[index] != state:
            self.input_mask[index] = state
            self.input_changed_ = True

    def getInput(self, input_name):
        #return self.input_state[input_name]
        index = self.input_dict[input_name]
        return self.input_mask[index]

    def setInputState(self, input_state):
        self.input_changed_ = True

        """
        keyList = []
        while input_state > 0:
            lastBase = 1
            base = 1
            while input_state > base:
                lastBase = base
                base *= 2

            input_state -= lastBase
            keyList.append(lastBase)

        for input_name, value in list(self.input_dict.items()):
            if value == 1:
                # 1 is reserved
                continue

            if value in keyList:
                self.input_state[input_name] = True
            else:
                self.input_state[input_name] = False
        """

        ## Need to confirm
        mask = list(bin(input_state))
        mask.remove('b')
        for i in range(0, len(mask)):
            self.input_mask[i] = int(mask[i])

    def getInputState(self):
        """
        #state = 0
        # Input ID 1 is reserved to make it work
        state = 1
        for input_name, value in list(self.input_dict.items()):
            if self.input_state[input_name]:
                state += value

        return state
        """

        ## Need to confirm
        return int(''.join(map(str, self.input_mask)))

    def getPredictedInputState(self):
        #state = 0
        # Input ID 1 is reserved to make it work
        state = 1
        for input_name, value in list(self.input_dict.items()):
            if self.predicted_input_state[input_name]:
                state += value

        return state

    def process_permission_(self, data):
        client_id = data[0]
        allowed = data[1]
        if allowed:
            self.givePermission(client_id)
        else:
            self.takePermission(client_id)

    def process_input_(self, data):
        state = data[0]
        self.setInputState(state)

    def hasPermission(self, client_id):
        return client_id in self.client_permission_list_

    def givePermission(self, client_id):
        if client_id in self.client_permission_list_:
            print ("Already has permission")
            return False
        else:
            print ("Giving permission")
            self.client_permission_list_.append(client_id)
            if self.mgr.hostmode == 'server':
                self.packer.pack('permission_', [client_id, 1])
            elif client_id == self.mgr.client_id:
                self.mgr.game.systems['Input'].setTarget(self)
            return True

    def takePermission(self, client_id):
        if client_id in self.client_permission_list_:
            print ("Taking permission")
            self.client_permission_list_.remove(client_id)
            if self.mgr.hostmode == 'server':
                self.packer.pack('permission_', [client_id, 0])
        else:
            print ("Did not have permission")
            return False

    # Virtual functions

    def c_register_setup(self):
        return

    def c_getStateData(self):
        return None

    def c_update(self, dt):
        return
        """
        if self.input_changed_:
            self.input_changed_ = False
            if self.mgr.hostmode == 'client':
                if self.mgr.game.systems['Input'].input_target is self:
                    state = self.getPredictedInputState()
                    self.packer.pack('input_', [state])

            else:
                state = self.getInputState()
                self.packer.pack('input_', [state])
        """

    def c_server_update(self, dt):
        return


class MainComponent(Component):
    def __init__(self, mgr, net_id):
        Component.__init__(self, mgr, net_id)
        self.ob_ = mgr.owner

        # new_net_id, new_net_id
        # posx, posy, posz
        # rotx, roty, rotz
        self.packer.registerPack('addComponent', self.addComponent,
            [Pack.USHORT, Pack.USHORT])

        self.packer.registerPack('setClientID', self.setClientID,
            [Pack.INT])

    def addComponent(self, data):
        net_id = data[0]
        comp_index = data[1]
        #pos = [data[2], data[3], data[4]]
        #ori = mathutils.Euler((data[5], data[6], data[7]))
        #input_state = data[8]

        self.mgr.spawnComponentByIndex(net_id, comp_index)
        #comp.setInputState(input_state)

    def setClientID(self, data):
        self.mgr.client_id = data[0]
