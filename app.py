from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import requests
import pymysql
from datetime import datetime
import logging

app = Flask(__name__, template_folder='templates')
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
app.logger = logging.getLogger(__name__)

# MySQL Configuration (WAMP)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:@localhost/cozy_distributor'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_POOL_RECYCLE'] = 299
app.config['SQLALCHEMY_POOL_SIZE'] = 20

db = SQLAlchemy(app)
MANUFACTURER_URL = 'http://localhost:5000/api'

# Database Models
class Inventory(db.Model):
    __tablename__ = 'inventory'
    id = db.Column(db.Integer, primary_key=True)
    blanket_model_id = db.Column(db.Integer, nullable=False, index=True)
    blanket_model_name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    purchase_price = db.Column(db.Float, nullable=False)
    selling_price = db.Column(db.Float, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'blanket_model_id': self.blanket_model_id,
            'blanket_model_name': self.blanket_model_name,
            'quantity': self.quantity,
            'purchase_price': self.purchase_price,
            'selling_price': self.selling_price
        }

class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, nullable=False, index=True)
    blanket_model_id = db.Column(db.Integer, nullable=False)
    blanket_model_name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), default='pending')
    order_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    fulfillment_date = db.Column(db.DateTime)

    def to_dict(self):
        result = {
            'id': self.id,
            'seller_id': self.seller_id,
            'blanket_model_id': self.blanket_model_id,
            'blanket_model_name': self.blanket_model_name,
            'quantity': self.quantity,
            'status': self.status
        }
        
        #  handle order_date
        if isinstance(self.order_date, datetime):
            result['order_date'] = self.order_date.strftime('%Y-%m-%d %H:%M:%S')
        elif self.order_date is not None:
            result['order_date'] = str(self.order_date)
        else:
            result['order_date'] = None
            
        # handle fulfillment_date
        if isinstance(self.fulfillment_date, datetime):
            result['fulfillment_date'] = self.fulfillment_date.strftime('%Y-%m-%d %H:%M:%S')
        elif self.fulfillment_date is not None:
            result['fulfillment_date'] = str(self.fulfillment_date)
        else:
            result['fulfillment_date'] = None
            
        return result

# Initialize Database
with app.app_context():
    db.create_all()

def validate_inventory_data(data):
    required_fields = ['blanket_model_id', 'quantity', 'purchase_price', 'selling_price']
    return all(field in data for field in required_fields)

@app.route('/')
def index():
    return render_template('distributor.html')

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    try:
        inventory = Inventory.query.all()
        return jsonify([item.to_dict() for item in inventory])
    except Exception as e:
        app.logger.error(f"Error in get_inventory: {str(e)}")
        return jsonify({'error': 'Failed to retrieve inventory'}), 500

@app.route('/api/inventory/<int:id>', methods=['GET'])
def get_inventory_item(id):
    try:
        item = Inventory.query.get_or_404(id)
        return jsonify(item.to_dict())
    except Exception as e:
        app.logger.error(f"Error in get_inventory_item: {str(e)}")
        return jsonify({'error': 'Inventory item not found'}), 404

@app.route('/api/inventory', methods=['POST'])
def add_inventory():
    try:
        data = request.json
        if not validate_inventory_data(data):
            return jsonify({'error': 'Missing required fields'}), 400

        # Verify blanket exists with manufacturer
        try:
            response = requests.get(
                f'{MANUFACTURER_URL}/blankets/{data["blanket_model_id"]}',
                timeout=3
            )
            if response.status_code != 200:
                return jsonify({'error': 'Blanket model not found with manufacturer'}), 404
            
            blanket = response.json()
            inventory = Inventory(
                blanket_model_id=data['blanket_model_id'],
                blanket_model_name=blanket['model_name'],
                quantity=data['quantity'],
                purchase_price=data['purchase_price'],
                selling_price=data['selling_price']
            )
            db.session.add(inventory)
            db.session.commit()
            return jsonify({
                'message': 'Inventory item added successfully',
                'data': inventory.to_dict()
            }), 201
            
        except requests.exceptions.RequestException as e:
            app.logger.error(f"Manufacturer service unavailable: {str(e)}")
            return jsonify({'error': 'Manufacturer service unavailable'}), 503
            
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error in add_inventory: {str(e)}")
        return jsonify({'error': 'Failed to add inventory item'}), 500

@app.route('/api/inventory/<int:id>', methods=['PUT'])
def update_inventory(id):
    try:
        inventory = Inventory.query.get_or_404(id)
        data = request.json
        
        if 'quantity' in data:
            inventory.quantity = data['quantity']
        if 'purchase_price' in data:
            inventory.purchase_price = data['purchase_price']
        if 'selling_price' in data:
            inventory.selling_price = data['selling_price']
            
        db.session.commit()
        return jsonify({
            'message': 'Inventory item updated successfully',
            'data': inventory.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error in update_inventory: {str(e)}")
        return jsonify({'error': 'Failed to update inventory item'}), 500

@app.route('/api/inventory/<int:id>', methods=['DELETE'])
def delete_inventory(id):
    try:
        inventory = Inventory.query.get_or_404(id)
        db.session.delete(inventory)
        db.session.commit()
        return jsonify({'message': 'Inventory item deleted successfully'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error in delete_inventory: {str(e)}")
        return jsonify({'error': 'Failed to delete inventory item'}), 500

@app.route('/api/orders', methods=['GET'])
def get_orders():
    try:
        # Get query parameters for filtering
        seller_id = request.args.get('seller_id')
        status = request.args.get('status')
        limit = request.args.get('limit', 50, type=int)
        
        
        query = Order.query
        
        # Apply filters 
        if seller_id:
            query = query.filter(Order.seller_id == seller_id)
        if status:
            query = query.filter(Order.status == status)
            
        # Get results ordered by most recent first
        orders = query.order_by(Order.order_date.desc()).limit(limit).all()
        
        # Convert to dictionary format 
        orders_data = []
        for order in orders:
            try:
                orders_data.append(order.to_dict())
            except Exception as e:
                app.logger.error(f"Error serializing order {order.id}: {str(e)}")
                continue
                
        return jsonify(orders_data)
    except Exception as e:
        app.logger.error(f"Error in get_orders: {str(e)}")
        return jsonify({'error': 'Failed to retrieve orders'}), 500

@app.route('/api/orders/<int:id>', methods=['GET'])
def get_order(id):
    try:
        order = Order.query.get_or_404(id)
        return jsonify(order.to_dict())
    except Exception as e:
        app.logger.error(f"Error in get_order: {str(e)}")
        return jsonify({'error': 'Order not found'}), 404

@app.route('/api/orders/<int:id>', methods=['PUT'])
def update_order(id):
    try:
        order = Order.query.get_or_404(id)
        data = request.json
        
        if 'status' in data:
            order.status = data['status']
            if data['status'] == 'fulfilled':
                order.fulfillment_date = datetime.utcnow()
        
        db.session.commit()
        return jsonify({
            'message': 'Order updated successfully',
            'order': order.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error in update_order: {str(e)}")
        return jsonify({'error': 'Failed to update order'}), 500

@app.route('/api/orders', methods=['POST'])
def create_order():
    try:
        data = request.json
        required_fields = ['seller_id', 'blanket_model_id', 'quantity']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        # Get blanket model name from inventory or manufacturer
        blanket_model_name = None
        inventory_item = Inventory.query.filter_by(blanket_model_id=data['blanket_model_id']).first()
        
        if inventory_item:
            blanket_model_name = inventory_item.blanket_model_name
        else:
            try:
                response = requests.get(
                    f'{MANUFACTURER_URL}/blankets/{data["blanket_model_id"]}',
                    timeout=3
                )
                if response.status_code == 200:
                    blanket_model_name = response.json().get('model_name', 'Unknown')
            except requests.exceptions.RequestException as e:
                app.logger.error(f"Error contacting manufacturer: {str(e)}")

        # Try to fulfill from distributor inventory first
        if inventory_item and inventory_item.quantity >= data['quantity']:
            inventory_item.quantity -= data['quantity']
            order = Order(
                seller_id=data['seller_id'],
                blanket_model_id=data['blanket_model_id'],
                blanket_model_name=blanket_model_name or 'Unknown',
                quantity=data['quantity'],
                status='fulfilled',
                fulfillment_date=datetime.utcnow()
            )
            db.session.add(order)
            db.session.commit()
            return jsonify({
                'message': 'Order fulfilled from distributor inventory',
                'order': order.to_dict()
            }), 201
        
        # Try to fulfill from manufacturer if not enough inventory
        try:
            response = requests.post(
                f'{MANUFACTURER_URL}/orders',
                json={
                    'seller_id': data['seller_id'],
                    'blanket_model_id': data['blanket_model_id'],
                    'quantity': data['quantity']
                },
                timeout=5
            )
            
            if response.status_code == 201:
                response_data = response.json()
                order = Order(
                    seller_id=data['seller_id'],
                    blanket_model_id=data['blanket_model_id'],
                    blanket_model_name=blanket_model_name or 'Unknown',
                    quantity=data['quantity'],
                    status=response_data.get('status', 'fulfilled'),
                    fulfillment_date=datetime.utcnow() if response_data.get('fulfilled') else None
                )
                db.session.add(order)
                db.session.commit()
                return jsonify({
                    'message': 'Order fulfilled from manufacturer',
                    'order': order.to_dict()
                }), 201
            else:
                return handle_backorder(data, blanket_model_name)
                
        except requests.exceptions.RequestException as e:
            app.logger.error(f"Manufacturer service error: {str(e)}")
            return handle_backorder(data, blanket_model_name, str(e))
            
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error in create_order: {str(e)}")
        return jsonify({'error': 'Failed to create order'}), 500

@app.route('/api/orders/<int:id>/fulfill', methods=['POST'])
def fulfill_order(id):
    try:
        order = Order.query.get_or_404(id)
        if order.status != 'pending':
            return jsonify({'error': 'Only pending orders can be fulfilled'}), 400
            
        # Check if we now have inventory to fulfill
        inventory_item = Inventory.query.filter_by(blanket_model_id=order.blanket_model_id).first()
        
        if inventory_item and inventory_item.quantity >= order.quantity:
            inventory_item.quantity -= order.quantity
            order.status = 'fulfilled'
            order.fulfillment_date = datetime.utcnow()
            db.session.commit()
            return jsonify({
                'message': 'Order fulfilled from distributor inventory',
                'order': order.to_dict()
            })
        
        # Try to fulfill from manufacturer
        try:
            response = requests.post(
                f'{MANUFACTURER_URL}/orders',
                json={
                    'seller_id': order.seller_id,
                    'blanket_model_id': order.blanket_model_id,
                    'quantity': order.quantity
                },
                timeout=5
            )
            
            if response.status_code == 201:
                response_data = response.json()
                order.status = response_data.get('status', 'fulfilled')
                order.fulfillment_date = datetime.utcnow() if response_data.get('fulfilled') else None
                db.session.commit()
                return jsonify({
                    'message': 'Order fulfilled from manufacturer',
                    'order': order.to_dict()
                })
            else:
                return jsonify({
                    'error': 'Unable to fulfill order',
                    'order': order.to_dict()
                }), 400
                
        except requests.exceptions.RequestException as e:
            app.logger.error(f"Manufacturer service error: {str(e)}")
            return jsonify({
                'error': 'Manufacturer service unavailable',
                'order': order.to_dict()
            }), 503
            
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error in fulfill_order: {str(e)}")
        return jsonify({'error': 'Failed to fulfill order'}), 500

@app.route('/api/orders/<int:id>/cancel', methods=['POST'])
def cancel_order(id):
    try:
        order = Order.query.get_or_404(id)
        if order.status != 'pending':
            return jsonify({'error': 'Only pending orders can be cancelled'}), 400
            
        order.status = 'cancelled'
        db.session.commit()
        
        return jsonify({
            'message': 'Order cancelled successfully',
            'order': order.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error in cancel_order: {str(e)}")
        return jsonify({'error': 'Failed to cancel order'}), 500

def handle_backorder(data, blanket_model_name, error_msg=None):
    order = Order(
        seller_id=data['seller_id'],
        blanket_model_id=data['blanket_model_id'],
        blanket_model_name=blanket_model_name or 'Unknown',
        quantity=data['quantity'],
        status='backordered'
    )
    db.session.add(order)
    db.session.commit()
    
    message = 'Order backordered'
    if error_msg:
        message += f' (Manufacturer unavailable: {error_msg})'
        
    return jsonify({
        'message': message,
        'order': order.to_dict()
    }), 202

if __name__ == '__main__':
    app.run(port=5001, debug=True, use_reloader=False)