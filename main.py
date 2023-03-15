from datetime import datetime, timedelta
import enum
import jwt
from decouple import config
from flask import Flask, request
from flask_migrate import Migrate
from flask_restful import Api, Resource
from flask_sqlalchemy import SQLAlchemy
from jwt import DecodeError, InvalidSignatureError
from sqlalchemy import func
from marshmallow import Schema, fields, validate, ValidationError, validates
from password_strength import PasswordPolicy
from werkzeug.exceptions import BadRequest, InternalServerError, Forbidden
from werkzeug.security import generate_password_hash
from marshmallow_enum import EnumField
from flask_httpauth import HTTPTokenAuth

app = Flask(__name__)

db_user = config('DB_USER')
db_password = config("DB_PASSWORD")
db_port = config('DB_PORT')
db_name = config('DB_NAME')

app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{db_user}:{db_password}@localhost:{db_port}/{db_name}'

db = SQLAlchemy(app)
api = Api(app)
migrate = Migrate(app, db)

auth = HTTPTokenAuth(scheme='Bearer')


def permission_required(permission_needed):
    def decorated_func(func):
        def wrapper(*args, **kwargs):
            if auth.current_user().role == permission_needed:
                return func(*args, **kwargs)
            raise Forbidden("Tou have no permission to access this resource.")

        return wrapper

    return decorated_func


@auth.verify_token
def verify_token(token):
    token_decoded_data = User.decode_token(token)
    user = User.query.filter_by(id=token_decoded_data["sub"]).first()
    return user


class UserRolesEnum(enum.Enum):
    super_admin = "super admin"
    admin = "admin"
    user = "user"


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.Text)
    role = db.Column(db.Enum(UserRolesEnum), server_default=UserRolesEnum.user.name, nullable=False)
    create_on = db.Column(db.DateTime, server_default=func.now())
    updated_on = db.Column(db.DateTime, onupdate=func.now())

    def encode_token(self):
        payload = {
            "sub": self.id,
            "exp": datetime.utcnow() + timedelta(days=2)
        }
        return jwt.encode(payload, key=config("SECRET_KEY"), algorithm="HS256")

    @staticmethod
    def decode_token(token):
        try:
            return jwt.decode(token, key=config("SECRET_KEY"), algorithms=["HS256"])
        except (DecodeError, InvalidSignatureError) as ex:
            raise BadRequest("Invalid or missing token!")
        except Exception:
            raise InternalServerError("Something went wrong!")


class ColorEnum(enum.Enum):
    pink = "pink"
    black = "black"
    white = "white"
    yellow = "yellow"


class SizeEnum(enum.Enum):
    xs = "xs"
    s = "s"
    m = "m"
    l = "l"
    xl = "xl"
    xxl = "xxl"


class Clothes(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    color = db.Column(db.Enum(ColorEnum), default=ColorEnum.white, nullable=False)
    size = db.Column(db.Enum(SizeEnum), default=SizeEnum.s, nullable=False)
    photo = db.Column(db.String(255), nullable=False)
    create_on = db.Column(db.DateTime, server_default=func.now())
    updated_on = db.Column(db.DateTime, onupdate=func.now())


def validate_name(name):
    try:
        first_name, last_name = name.split()
    except ValueError:
        raise ValidationError("At least two names are required!")


policy = PasswordPolicy.from_names(
    uppercase=1,  # need min. 1 uppercase letters
    numbers=1,  # need min. 1 digits
    special=1,  # need min. 1 special characters
    nonletters=1,  # need min. 1 non-letter characters (digits, specials, anything)
)


def validate_password(value):
    errors = policy.test(value)
    if errors:
        raise ValidationError(f"Not a valid password")


class BaseUserSchema(Schema):
    email = fields.Email(required=True)
    full_name = fields.String(required=True)

    @validates("full_name")
    def validate_name(self, name):
        if not (3 < len(name) < 255):
            raise ValidationError("Length must be between 3 and 255")
        try:
            first_name, last_name = name.split()
        except ValueError:
            raise ValidationError("At least two names are required!")


class UserSignInSchema(BaseUserSchema):
    password = fields.String(required=True, validate=validate_password)


class UserOutSchema(BaseUserSchema):
    id = fields.Integer()
    # full_name = fields.String()
    # clothes = fields.List(fields.Nested(SingleClothSchema), many=True)


class SingleClothSchemaBase(Schema):
    name = fields.String(required=True)
    color = EnumField(ColorEnum, by_value=True)
    size = EnumField(SizeEnum, by_value=True)


class SingleClothSchemaIn(SingleClothSchemaBase):
    photo = fields.String(required=True)


class SingleClothSchemaOut(SingleClothSchemaBase):
    id = fields.Integer()
    create_on = fields.DateTime()
    updated_on = fields.DateTime()


class UserRegisterResource(Resource):
    def post(self):
        data = request.get_json()
        schema = UserSignInSchema()
        errors = schema.validate(data)
        if not errors:
            data["password"] = generate_password_hash(data['password'], method='sha256')
            user = User(**data)
            db.session.add(user)
            db.session.commit()
            return {"token": user.encode_token()}
        return errors


class ClothesResource(Resource):
    @auth.login_required
    @permission_required(UserRolesEnum.admin)
    def post(self):
        data = request.get_json()
        # current_user = auth.current_user()
        schema = SingleClothSchemaIn()
        errors = schema.validate(data)
        if errors:
            return errors
        clothes = Clothes(**data)
        db.session.add(clothes)
        db.session.commit()
        return SingleClothSchemaOut().dump(clothes)


users_clothes = db.Table(
    "users_clothes",
    db.Model.metadata,
    db.Column("user_id", db.Integer, db.ForeignKey("user.id")),
    db.Column("clothes_id", db.Integer, db.ForeignKey("clothes.id")), )

api.add_resource(UserRegisterResource, "/register")
api.add_resource(ClothesResource, "/clothes")

if __name__ == "__main__":
    app.run(debug=True)
