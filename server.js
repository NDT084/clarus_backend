const express = require('express');
const cors = require('cors');
const mysql = require('mysql2/promise');

const app = express();
app.use(cors());
app.use(express.json());

// --------- CONFIG MySQL ---------
const pool = mysql.createPool({
  host: 'localhost',
  user: 'daniel',        // ton user MySQL
  password: 'daniel777', // ton mot de passe
  database: 'clarus_chat', // ta base (chat_messages + chat_sessions)
  waitForConnections: true,
  connectionLimit: 10,
  queueLimit: 0,
});

// Test de connexion
(async () => {
  try {
    const conn = await pool.getConnection();
    console.log('MySQL connecté');
    conn.release();
  } catch (err) {
    console.error('Erreur connexion MySQL:', err);
  }
})();

// --------- POST /messages : enregistre user + assistant ---------
app.post('/messages', async (req, res) => {
  console.log('POST /messages reçu, body =', req.body);

  try {
    const { session_id, user_id, user_message, assistant_reply } = req.body;

    if (!session_id || !user_message || !assistant_reply) {
      console.warn('Requête /messages invalide:', req.body);
      return res
        .status(400)
        .json({ error: 'session_id, user_message, assistant_reply requis' });
    }

    const conn = await pool.getConnection();
    try {
      await conn.beginTransaction();

      // 1) Créer la session si elle n'existe pas encore
      //    user_id peut être null pour le moment
      const sessionTitle = user_message.slice(0, 80); // titre = début du premier message

      await conn.execute(
        `INSERT IGNORE INTO chat_sessions (session_id, user_id, title)
         VALUES (?, ?, ?);`,
        [session_id, user_id || null, sessionTitle]
      );

      // 2) Insérer message user
      await conn.execute(
        `INSERT INTO chat_messages (session_id, user_id, role, content)
         VALUES (?, ?, 'user', ?)`,
        [session_id, user_id || null, user_message]
      );

      // 3) Insérer message assistant
      await conn.execute(
        `INSERT INTO chat_messages (session_id, user_id, role, content)
         VALUES (?, ?, 'assistant', ?)`,
        [session_id, user_id || null, assistant_reply]
      );

      await conn.commit();
      res.status(201).json({ status: 'ok' });
    } catch (err) {
      await conn.rollback();
      console.error('Erreur insert messages:', err);
      res.status(500).json({ error: 'Erreur serveur' });
    } finally {
      conn.release();
    }
  } catch (err) {
    console.error('Erreur /messages:', err);
    res.status(500).json({ error: 'Erreur serveur' });
  }
});

// --------- GET /history/:sessionId : retourne l’historique ---------
app.get('/history/:sessionId', async (req, res) => {
  const sessionId = req.params.sessionId;

  try {
    const [rows] = await pool.execute(
      `SELECT role, content, created_at
       FROM chat_messages
       WHERE session_id = ?
       ORDER BY created_at ASC`,
      [sessionId]
    );

    res.json(rows);
  } catch (err) {
    console.error('Erreur /history:', err);
    res.status(500).json({ error: 'Erreur serveur' });
  }
});

// --------- GET /sessions : liste des conversations ---------
// Pour l'instant sans filtre user_id, on renvoie tout
app.get('/sessions', async (req, res) => {
  try {
    const [rows] = await pool.execute(
      `SELECT id, session_id, user_id, title, created_at
       FROM chat_sessions
       ORDER BY created_at DESC`
    );

    res.json(rows);
  } catch (err) {
    console.error('Erreur /sessions:', err);
    res.status(500).json({ error: 'Erreur serveur' });
  }
});

const PORT = 4000;
app.listen(PORT, () => {
  console.log(`API Clarus chat MySQL sur http://localhost:${PORT}`);
});
