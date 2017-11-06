import json
import struct
import six

from base58 import b58decode
from collections import namedtuple
import datetime
import uplink.enum as enum
from uplink.cryptography import (ecdsa_sign, derive_asset_address)


# ------------------------------------------------------------------------
# Serializers
# ------------------------------------------------------------------------


class Serializer(object):

    @staticmethod
    def serialize(object, **kwargs):
        return json.dumps(object, **kwargs)


def _to_dict(obj, classkey=None, *args, **kwargs):
    if isinstance(obj, dict):
        data = {}
        for (k, v) in obj.items():
            data[k] = _to_dict(v, classkey)
        return data

    elif hasattr(obj, "_asdict"):
        return _to_dict(obj._asdict())
    elif hasattr(obj, "_ast"):
        return _to_dict(obj._ast())
    elif hasattr(obj, "__iter__") and not (isinstance(obj, str) or isinstance(obj, bytes)):
        return [_to_dict(v, classkey) for v in obj]
    elif hasattr(obj, "__dict__"):

        data = dict([(key, _to_dict(value, classkey))
                     for key, value in six.iteritems(obj.__dict__)
                     if not callable(value) and not key.startswith('_')])

        if classkey is not None and hasattr(obj, "__class__"):
            data[classkey] = obj.__class__.__name__
        return data
    else:
        if isinstance(obj, bytes):
            obj = obj.decode()
        return obj


class Serializable(object):

    def to_dict(self, *args, **kwargs):
        return _to_dict(self, *args, **kwargs)

    def to_binary(self):
        raise NotImplementedError

    def to_json(self, **kwargs):
        return Serializer.serialize(self.to_dict(), **kwargs)

    def sign(self, privkey, k=None):
        stream = self.to_binary()
        return ecdsa_sign(privkey, stream, k=k)


class Tagged(object):

    def __dict__(self):
        result = super(Tagged, self).__dict__
        result['tag'] = type(self).__name__
        return result

    def _asdict(self):
        result = super(Tagged, self)._asdict()
        result['tag'] = type(self).__name__
        return result


# ------------------------------------------------------------------------
# Uplink Protocol
# ------------------------------------------------------------------------


class Block(Serializable):
    """Block Object"""

    def __init__(self, header, signatures, index, transactions):
        self.header = BlockHeader(header)
        self.transactions = transactions
        self.index = index
        self.signatures = signatures
        self.addr = None

    def __repr__(self):
        return "<Block(index=%i)>" % self.index


class BlockHeader(Serializable):
    """Header child Object"""

    def __init__(self, header):
        self.origin = header['origin']
        self.merkleRoot = header['merkleRoot']
        self.timestamp = header['timestamp']
        self.prevHash = header['prevHash']


class Peer(object):
    """Peer Object"""

    def __init__(self, tag, contents):
        self.tag = tag
        self.contents = PeerContents(contents)

    def __repr__(self):
        return "<Peer(contents=%s)>" % self.contents


class PeerContents(object):
    """Peer Contents Object"""

    def __init__(self, contents):
        self.peer_pid = contents['peerPid']
        self.peer_acc_addr = contents['peerAccAddr']


class Account(object):
    """Account Object"""

    def __init__(self, timezone, publicKey, metadata, address):
        self.timezone = timezone
        self.public_key = publicKey
        self.address = address

        assert type(metadata) is dict

        if metadata is not None:
            self.metadata = {k: v for k, v in six.iteritems(metadata)}
        else:
            self.metadata = {}

    def __repr__(self):
        return "<Account(addr=%s)>" % self.address


class Asset(Serializable):
    """Asset Object"""

    def __init__(self, address, issuedOn, assetType, name, reference, supply, holdings, issuer):
        self.address = address
        self.issuedOn = issuedOn
        self.assetType = AssetType(assetType)
        self.name = name
        self.reference = reference
        self.supply = supply
        self.holdings = holdings
        self.issuer = issuer

    def __repr__(self):
        return "<Asset(name=%s)>" % self.name


class Assets(Serializable):
    """Asset List Object"""

    def __init__(self, asset, address):
        self.address = address
        self.name = asset['name']
        self.issuer = asset['issuer']
        self.issuedOn = asset['issuedOn']
        self.supply = asset['supply']
        self.holdings = asset['holdings']
        self.reference = asset['reference']
        self.assetType = AssetType(asset['assetType'])

    def __repr__(self):
        return "<Assets(address=%s)>" % self.address


class AssetType(Serializable):
    """Asset Type"""

    def __init__(self, asset_type):
        asset_types = ["Fractional", "Discrete", "Binary"]
        if asset_type['type'] in asset_types:
            self.type = asset_type['type']
            if self.type == enum.AssetFractional:
                if asset_type['precision'] in [x for x in range(1, 7)]:
                    self.precision = asset_type['precision'] or None
                else:
                    self.precision = None
                    valerr = "Invalid precision for Fractional asset type."
                    raise ValueError(valerr)
            elif asset_type["precision"] is not None:
                self.precision = None
                valerr = "Cannot specify precision of Non-Fractional asset."
                raise ValueError(valerr)
            else:
                self.precision = None
        else:
            self.type = asset_type['type']
            self.precision = None
            raise ValueError("Invalid asset type: " + asset_type['type'])

    def to_binary(self):
        fmt = ">H{}s".format(len(self.type))
        typ = struct.pack(fmt, len(self.type), self.type.encode())

        prec = self.precision
        mprec = b'' if prec is None else struct.pack(">q", self.precision)
        return (typ + mprec)


class AssetRef(Serializable):
    """Asset Ref"""

    def __init__(self, asset_ref):
        if asset_ref in ["USD", "GBP", "EUR", "CHF", "Token", "Security"]:
            self.ref = asset_ref
        else:
            raise ValueError(str(asset_ref) + "is not a valid asset reference")

    def to_binary(self):
        fmt = ">H{}s".format(len(self.type))
        byts = struct.pack(fmt, len(self.ref))
        return struct.pack(fmt, len(self.ref), byts)


class VInt(Tagged, Serializable, namedtuple("VInt", 'contents')):

    def to_binary(self):
        return struct.pack('>bq', enum.VTypeInt, self.contents)


class VFloat(Tagged, Serializable, namedtuple('VFloat', 'contents')):

    def to_binary(self):
        return struct.pack('>bd', enum.VTypeFloat, self.contents)


class VBool(Tagged, Serializable, namedtuple('VBool', 'contents')):

    def to_binary(self):
        return struct.pack('>b?', enum.VTypeBool, self.contents)


class VAddress(Tagged, Serializable, namedtuple('VAddress', 'contents')):

    def to_binary(self):
        return struct.pack('>b32s', enum.VTypeAddress, b58decode(self.contents))


class VAccount(Tagged, Serializable, namedtuple('VAccount', 'contents')):

    def to_binary(self):
        return struct.pack('>b32s', enum.VTypeAccount, b58decode(self.contents))


class VAsset(Tagged, Serializable, namedtuple('VAsset', 'contents')):

    def to_binary(self):
        return struct.pack('>b32s', enum.VTypeAsset, b58decode(self.contents))


class VContract(Tagged, Serializable, namedtuple('VContract', 'contents')):

    def to_binary(self):
        return struct.pack('>b32s', enum.VTypeContract, b58decode(self.contents))


class VMsg(Tagged, Serializable, namedtuple('VMsg', 'contents')):

    def to_binary(self):
        return struct.pack('>bH{}s'.format(str(len(self.contents))), enum.VTypeMsg, len(self.contents), self.contents.encode())


class VVoid(Tagged, Serializable, namedtuple('VVoid', '')):

    def to_binary(self):
        return struct.pack('>b', enum.VTypeVoid)


VVoid = VVoid()


class VDateTime(Tagged, Serializable, namedtuple('VDateTime', 'contents')):

    def to_binary(self):
        year = self.contents.year
        month = self.contents.month
        day = self.contents.day
        hour = self.contents.hour
        minute = self.contents.minute
        second = self.contents.second
        tz = self.contents.tzinfo
        dayofweek = datetime.date(year, month, day).weekday()

        return struct.pack('>bQQQQQQQQ', enum.VTypeDateTime, year, month, day, hour, minute, second, tz, dayofweek)


class VTimeDelta(Tagged, Serializable, namedtuple('VTimeDelta', 'contents')):

    def to_binary(self):
        year = self.contents.year
        month = self.contents.month
        day = self.contents.day
        hour = self.contents.hour
        minute = self.contents.minute
        second = self.contents.second
        nanosec = self.contents.microsecond * 1000
        return struct.pack('>bQQQQQQQ', enum.VTypeTimeDelta, year, month, day, hour, minute, second, nanosec)


class VUndefined(Tagged, Serializable, namedtuple('VUndefined', '')):

    def to_binary(self):
        return struct.pack('>b', enum.VTypeUndefined)


VUndefined = VUndefined()


class Contract(Serializable):
    """Contracts Object"""

    def __init__(self, timestamp, address, storage, methods, script, owner, terminated, state, **kwargs):
        self.timestamp = timestamp
        self.script = script
        self.storage = storage
        self.methods = methods
        self.address = address
        self.owner = owner
        self.terminated = terminated
        self.state = state

    def __repr__(self):
        return "<Contract(address=%s)>" % self.address


# ----------------------------------------------------------------------------
# Transactions and Header Objects
# ----------------------------------------------------------------------------


class Transaction(Serializable):
    """Transactions Object"""

    def __init__(self, header, signature, timestamp, origin):
        self.header = header
        self.signature = signature
        self.timestamp = timestamp
        self.origin = origin

    def __repr__(self):
        return "<Transaction(signature=%s)>" % self.signature


def tag_from_contents(contents):
    """Retrieve class name from function"""
    return contents.__class__.__name__


class TxAsset(Serializable):
    """Asset Transaction"""

    def __init__(self, contents):
        self.tag = tag_from_contents(self)
        self.contents = contents


class TxContract(Serializable):
    """Denoting contract creation transaction"""

    def __init__(self, contents):
        self.tag = tag_from_contents(self)
        self.contents = contents


class TxAccount(Serializable):
    """Account Transaction"""

    def __init__(self, contents):
        self.tag = tag_from_contents(self)
        self.contents = contents


# ------------------------------------------------------------------------
# Create Account
# ------------------------------------------------------------------------


class CreateAccount(Serializable):
    """Denoting account creation transaction"""

    def __init__(self, contents):
        self.tag = tag_from_contents(self)
        self.contents = contents


class CreateAccountHeader(Serializable):
    """Create account transaction header"""

    def __init__(self, new_pubkey, metadata, address, timezone):
        self.pubKey = new_pubkey
        self.timezone = timezone
        # self.address = address
        self.metadata = metadata
        assert type(metadata) is dict

    def to_binary(self):
        pack_timezone = str(len(self.timezone)) + "s"
        timezone_len = len(self.timezone)

        key_str = self.pubKey
        pack_pubkey = str(len(key_str)) + "s"
        pubkey_len = len(key_str)

        if len(self.metadata) > 0:

            package = ">HH" + pack_pubkey + "H" + pack_timezone
            structured = struct.pack(
                package, enum.TxTypeCreateAccount, pubkey_len, key_str, timezone_len, self.timezone.encode())

            len_pack = struct.pack(">H", len(self.metadata))
            structured = structured + len_pack

            meta_structure = b""

            for key in sorted(six.iterkeys(self.metadata)):
                value = self.metadata[key]
                pack_key = str(len(key)) + "s"
                key_len = len(key)

                pack_value = str(len(value)) + "s"
                value_len = len(value)

                metapack = (">H" + pack_key + "H" + pack_value).encode()

                meta_structure = meta_structure + \
                    struct.pack(metapack, key_len, key.encode(),
                                value_len, value.encode())

            structured = structured + meta_structure

        else:
            package = ">HH" + pack_pubkey + "H" + pack_timezone + "H"
            structured = struct.pack(package, enum.TxTypeCreateAccount,
                                     pubkey_len, self.pubKey, timezone_len,
                                     self.timezone.encode(), 0)

        return structured


# ------------------------------------------------------------------------
# CreateAsset
# ------------------------------------------------------------------------


class CreateAsset(Serializable):
    """Denotes asset creation transaction"""

    def __init__(self, contents):
        self.tag = tag_from_contents(self)
        self.contents = contents


class CreateAssetHeader(Serializable):
    """Create Asset Header"""

    def __init__(self, name, supply, asset_type, reference, issuer, precision):
        asset_type_ = AssetType(dict(type=asset_type, precision=precision))
        self.assetAddr = derive_asset_address(name, issuer, supply, reference,
                                              asset_type_)
        self.assetName = name
        self.supply = int(supply)
        self.issuer = issuer
        self.reference = str(reference)
        self.assetType = AssetTypeParams(asset_type, precision)

    def to_binary(self):
        precision = self.assetType.contents
        _asset_type = bytes(self.assetType.tag)
        name_len = str(len(self.assetName)) + "s"
        asset_len = str(len(_asset_type)) + "s"
        reference_len = str(len(self.reference)) + "s"

        if _asset_type == 'Fractional':
            package = ">H32sH" + name_len + "QHH" + reference_len + "H" + asset_len + "Q"
            structured = struct.pack(
                package,
                enum.TxTypeCreateAsset,
                b58decode(self.assetAddr),
                len(self.assetName),
                self.assetName.encode(),
                self.supply,
                1,
                len(self.reference),
                self.reference.encode(),
                len(_asset_type),
                _asset_type,
                int(precision))
        else:
            package = ">H32sH" + name_len + "QHH" + reference_len + "H" + asset_len
            structured = struct.pack(
                package,
                enum.TxTypeCreateAsset,
                b58decode(self.assetAddr),
                len(self.assetName),
                self.assetName.encode(),
                self.supply,
                1,
                len(self.reference),
                self.reference.encode(),
                len(_asset_type),
                _asset_type)

        return structured


class AssetTypeParams(Serializable):
    """Asset Type"""

    def __init__(self, type_, precision):
        self.tag = type_.encode()
        self.contents = precision


# ------------------------------------------------------------------------
# Contracts
# ------------------------------------------------------------------------


class CreateContract(Serializable):
    """Denoting creation (contract, asset, account) transaction"""

    def __init__(self, contents):
        self.tag = tag_from_contents(self)
        self.contents = contents


class CreateContractHeader(Serializable):
    """Contract Creation Header"""

    def __init__(self, script, owner, address, timestamp, storage=None, methods=None):
        # self.contract = ContractParams(
        #     script, address, timestamp, storage, methods)
        self.script = str(script)
        self.owner = str(owner)
        self.address = str(address)
        self.timestamp = timestamp

    def to_binary(self):
        pack_script = str(len(self.script)) + "s"
        pack_len = len(self.script)
        address = b58decode(self.address)

        structured = struct.pack(
            ">H32sH" + pack_script, enum.TxTypeCreateContract, address, pack_len, self.script.encode())

        return structured

        # class ContractParams(Serializable):
        #     """Contract Parameters Body"""

        #     def __init__(self, script, address, timestamp, storage=None, methods=None):
        #         self.script = script
        #         self.address = address
        #         self.timestamp = timestamp

        # self.storage = storage
        # self.methods = methods

        # assert type(methods) is list
        # assert type(storage) is dict


# ------------------------------------------------------------------------
# Memory Pool
# ------------------------------------------------------------------------


class MemPool(Serializable):
    """MemPool Transactions"""

    def __init__(self, mempool_dict):
        """Receive from RPC call"""
        self.size = mempool_dict["size"]

        txs = []
        for elem in mempool_dict["transactions"]:
            tx_header = elem["header"]
            origin = elem["origin"]
            signature = elem["signature"]
            timestamp = elem["timestamp"]

            tx = Transaction(tx_header, signature,
                             timestamp, origin=origin)
            txs.append(tx)
        self.transactions = txs

    def __repr__(self):
        return "<MemPool(size=%s)>" % self.size


# ------------------------------------------------------------------------
# Asset Transfer
# ------------------------------------------------------------------------


class Transfer(Serializable):
    """Transfer object"""

    def __init__(self, contents):
        self.tag = tag_from_contents(self)
        self.contents = contents


class TransferAssetHeader(Serializable):
    """Asset Transfer Header"""

    def __init__(self, assetAddr, toAddr, balance):
        self.assetAddr = assetAddr
        self.toAddr = toAddr
        self.balance = balance

    def to_binary(self):
        structured = struct.pack(
            ">H32s32sq", enum.TxTypeTransfer, b58decode(self.assetAddr), b58decode(self.toAddr), self.balance)
        return structured

# ------------------------------------------------------------------------
# Asset Circulate
# ------------------------------------------------------------------------


class Circulate(Serializable):
    """Circulate object"""

    def __init__(self, contents):
        self.tag = tag_from_contents(self)
        self.contents = contents


class CirculateAssetHeader(Serializable):
    """Asset Circulate Header"""

    def __init__(self, assetAddr, amount):
        self.assetAddr = assetAddr
        self.amount = amount

    def to_binary(self):
        structured = struct.pack(
            ">H32sq", enum.TxTypeCirculate, b58decode(self.assetAddr), self.amount)
        return structured

# ------------------------------------------------------------------------
# Revoke Account
# ------------------------------------------------------------------------


class RevokeAccount(Serializable):
    """Revoke Object"""

    def __init__(self, contents):
        self.tag = tag_from_contents(self)
        self.contents = contents


class RevokeAccountHeader(Serializable):
    """Revoke Account Header object"""

    def __init__(self, account_addr):
        self.address = account_addr

    def to_binary(self):
        structured = struct.pack(
            ">H32s", enum.TxTypeRevokeAccount, b58decode(self.address))
        return structured

# ------------------------------------------------------------------------
# Revoke Asset
# ------------------------------------------------------------------------


class RevokeAsset(Serializable):
    """Revoke Asset Object"""

    def __init__(self, contents):
        self.tag = tag_from_contents(self)
        self.contents = contents


class RevokeAssetHeader(Serializable):
    """Revoke Asset Header object"""

    def __init__(self, asset_addr):
        self.address = asset_addr

    def to_binary(self):
        structured = struct.pack(
            ">H32s", enum.TxTypeRevokeAsset, b58decode(self.address))
        return structured

# ------------------------------------------------------------------------
# Call Contract
# ------------------------------------------------------------------------


class Call(Serializable):
    """Call contract method object"""

    def __init__(self, contents):
        self.tag = tag_from_contents(self)
        self.contents = contents


class CallHeader(Serializable):
    """Denotes contract Call Header"""

    def __init__(self, contract_addr, method, args):
        self.address = contract_addr
        self.method = method
        self.args = args

    def to_binary(self):
        binary_args = b''.join([arg.to_binary() for arg in self.args])

        structured = struct.pack(
            ">H32sQ{}sQ{}s".format(str(len(self.method)), str(
                len(binary_args))), enum.TxTypeCall,
            b58decode(self.address),
            len(self.method), self.method.encode(), len(self.args), binary_args)
        return structured


# ------------------------------------------------------------------------
# Bind
# ------------------------------------------------------------------------


class Bind(Serializable):
    """Bind asset object"""

    def __init__(self, contents):
        self.tag = tag_from_contents(self)
        self.contents = contents


class BindHeader(Serializable):
    """Bind asset header"""

    def __init__(self, asset_addr, contract_addr, proof):
        self.asset = asset_addr
        self.contract = contract_addr
        self.proof = proof

    def to_binary(self):
        """Convert bytes for binding asset to a contract"""

        structured = struct.pack(
            ">H32s32s{}s".format(len(self.proof)),
            enum.TxTypeBind, self.contract.encode(), self.asset.encode(), self.proof)
        return structured


# ------------------------------------------------------------------------
# SyncLocal
# ------------------------------------------------------------------------


class SyncLocal(Serializable):
    """denotes sync local"""

    def __init__(self, contents):
        self.tag = tag_from_contents(self)
        self.contents = contents


class SyncHeader(Serializable):
    """denotes sync local header"""

    def __init__(self, contract_addr):
        self.contract = contract_addr

    def to_binary(self):
        """Convert bytes for syncing local contract"""
        structured = struct.pack(
            ">H32s", enum.TxTypeSyncLocal, self.contract)
        return structured
