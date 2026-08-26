-- Create games table
CREATE TABLE IF NOT EXISTS games (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title VARCHAR(255) NOT NULL,
  date_played DATE NOT NULL,
  location VARCHAR(255),
  video_file_path VARCHAR(512),
  video_duration_seconds INT,
  frame_count INT,
  processing_status VARCHAR(50) DEFAULT 'pending',
  processing_started_at TIMESTAMP,
  processing_completed_at TIMESTAMP,
  processing_error TEXT,
  home_team VARCHAR(100),
  away_team VARCHAR(100),
  total_shots INT DEFAULT 0,
  made_shots INT DEFAULT 0,
  total_rebounds INT DEFAULT 0,
  total_turnovers INT DEFAULT 0,
  total_assists INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Create frames table
CREATE TABLE IF NOT EXISTS frames (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id),
  frame_number INT NOT NULL,
  timestamp_seconds DECIMAL(10,2),
  local_file_path VARCHAR(512),
  width INT,
  height INT,
  processed_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(game_id, frame_number)
);

-- Create detected objects table
CREATE TABLE IF NOT EXISTS detected_objects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  frame_id UUID NOT NULL REFERENCES frames(id),
  object_type VARCHAR(50),
  confidence_score DECIMAL(5,3),
  bbox_x INT,
  bbox_y INT,
  bbox_width INT,
  bbox_height INT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Create game events table
CREATE TABLE IF NOT EXISTS game_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id),
  event_type VARCHAR(50),
  start_frame INT,
  end_frame INT,
  start_timestamp DECIMAL(10,2),
  end_timestamp DECIMAL(10,2),
  event_details JSONB,
  confidence_score DECIMAL(5,3),
  created_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_games_status ON games(processing_status);
CREATE INDEX IF NOT EXISTS idx_games_date ON games(date_played);
CREATE INDEX IF NOT EXISTS idx_frames_game ON frames(game_id);
CREATE INDEX IF NOT EXISTS idx_detected_objects_frame ON detected_objects(frame_id);
CREATE INDEX IF NOT EXISTS idx_game_events_game ON game_events(game_id);
CREATE INDEX IF NOT EXISTS idx_game_events_type ON game_events(event_type);

-- Create users table (optional, for auth later)
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) UNIQUE NOT NULL,
  full_name VARCHAR(255),
  password_hash VARCHAR(255),
  created_at TIMESTAMP DEFAULT NOW()
);

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO basketball_user;
