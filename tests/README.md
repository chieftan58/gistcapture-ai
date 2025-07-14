# Renaissance Weekly Test Suite

Comprehensive testing infrastructure for Renaissance Weekly podcast intelligence system.

## Quick Start

```bash
# Install test dependencies
pip install -e ".[test]"

# Run all tests
pytest

# Run with coverage
pytest --cov=renaissance_weekly

# Run specific test types
./run_tests.py --unit          # Fast unit tests only
./run_tests.py --integration   # Integration tests
./run_tests.py --e2e          # End-to-end tests

# Watch mode (re-runs on file changes)
./run_tests.py --watch

# Run tests in parallel
./run_tests.py -n 4
```

## Test Organization

```
tests/
├── unit/                     # Fast, isolated unit tests
│   ├── test_database.py     # Database operations
│   ├── test_episode_fetcher.py  # RSS/API fetching
│   └── test_summarizer.py   # AI summarization
├── integration/              # Component interaction tests  
│   ├── test_download_strategies.py  # Download system
│   └── test_transcript_finding.py   # Transcript sources
├── e2e/                      # Full pipeline tests
│   └── test_full_pipeline.py    # Complete workflows
├── fixtures/                 # Test data and mocks
│   └── test_data/           # Sample files
└── conftest.py              # Shared fixtures
```

## Key Features

### 1. **Comprehensive Fixtures** (conftest.py)
- Database setup and teardown
- Mock external services (OpenAI, AssemblyAI, SendGrid)
- Sample data factories
- Async testing utilities

### 2. **Realistic Test Data**
- Episode factory with random data
- Sample RSS feeds
- Mock API responses
- Performance profiling tools

### 3. **Test Categories**

**Unit Tests** (Fast, <1s each)
- Database CRUD operations
- Date calculations
- Data validation
- Business logic

**Integration Tests** (Medium, 1-5s)
- Download strategy routing
- Multi-source transcript finding
- API client interactions
- Error handling flows

**E2E Tests** (Slow, 5-30s)
- Complete pipeline execution
- Concurrency handling
- Failure recovery
- Caching behavior

### 4. **Mock Strategy**
- External APIs fully mocked
- Configurable failure scenarios
- Realistic response delays
- No actual network calls

## Writing Tests

### Basic Test Structure

```python
import pytest
from renaissance_weekly.models import Episode

class TestFeatureName:
    """Test feature description"""
    
    @pytest.mark.unit
    def test_specific_behavior(self, test_db, create_episode):
        """Test that specific behavior works correctly"""
        # Arrange
        episode = create_episode(podcast="Test Show")
        
        # Act
        result = some_function(episode)
        
        # Assert
        assert result.success is True
        assert result.data == expected_data
```

### Async Test Pattern

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_operation(self, mock_openai):
    """Test async operation"""
    # Arrange
    mock_openai.chat.completions.create = AsyncMock(
        return_value=mock_response
    )
    
    # Act
    result = await async_function()
    
    # Assert
    assert result is not None
    mock_openai.chat.completions.create.assert_called_once()
```

### Testing Error Scenarios

```python
@pytest.mark.unit
def test_handles_errors_gracefully(self):
    """Test error handling"""
    with pytest.raises(ValueError, match="Invalid podcast"):
        process_invalid_podcast(None)
```

## Coverage Goals

- **Target**: 85% overall coverage
- **Current**: Run `pytest --cov` to check
- **Priority Areas**:
  1. Core business logic (90%+)
  2. Error handling paths (80%+)
  3. API integrations (75%+)
  4. UI endpoints (70%+)

## Performance Testing

```python
def test_performance_benchmark(benchmark_timer):
    """Test operation completes within time limit"""
    with benchmark_timer as timer:
        result = expensive_operation()
    
    assert timer.elapsed < 2.0  # Should complete in 2 seconds
    assert result is not None
```

## Debugging Tests

```bash
# Run single test with output
pytest -vs tests/unit/test_database.py::test_save_episode

# Drop into debugger on failure
pytest --pdb

# Show local variables on failure
pytest -l

# Maximum verbosity
pytest -vvv
```

## CI/CD Integration

Tests run automatically on:
- Every push to main
- All pull requests
- Nightly full suite runs

Failed tests block deployment.

## Common Issues

1. **Import Errors**: Ensure project is installed with `pip install -e .`
2. **Async Warnings**: Use `pytest-asyncio` fixtures
3. **Database Locks**: Each test gets isolated database
4. **Flaky Tests**: Mark with `@pytest.mark.flaky` and fix later

## Best Practices

1. **Keep tests fast** - Mock external calls
2. **Test one thing** - Single assertion per test ideal
3. **Use fixtures** - Don't repeat setup code
4. **Name clearly** - `test_<what>_<condition>_<expected>`
5. **Isolate tests** - No shared state between tests
6. **Document why** - Explain complex test scenarios