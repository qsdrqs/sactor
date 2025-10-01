// From Project c_fsm, under MIT license

/* forward declaration for typedefs */
struct cfsm_Ctx;

/**
 * @brief Function pointer type for enter/leave operations.
 *
 */
typedef void (*cfsm_TransitionFunction)(struct cfsm_Ctx * fsm);

/**
 * @brief Function pointer type for event signal operation.
 *
 */
typedef void (*cfsm_EventFunction)(struct cfsm_Ctx * fsm, int eventId);

/**
 * @brief  * @brief Function pointer type for cyclic process operation.
 *
 */
typedef void (*cfsm_ProcessFunction)(struct cfsm_Ctx * fsm);

/**
 * @brief Instance data pointer as void * to accept any pointer type.
 *
 */

/** The CFSM context data structure
*/
struct cfsm_Ctx {
    void *    ctxPtr;    /**< Context instance data        */
    cfsm_TransitionFunction onLeave;   /**< Operation to run on leave    */
    cfsm_ProcessFunction    onProcess; /**< Cyclic processoperation      */
    cfsm_EventFunction      onEvent;   /**< Report event to active state */
};

// From Project c-aces, under MIT license
#include <stdint.h>

struct Parameters {
  uint64_t dim;
  uint64_t N;
};

/**
 * @brief Represents an arithmetic channel.
 *
 * An arithmetic channel consists of a tuple (p, q, ω, u) where:
 * 1) p, q, and ω are positive integers such that p < q;
 * 2) u is a polynomial in Z[X] such that u(ω) = q.
 *
 * @param p The positive integer 'p'.
 * @param q The positive integer 'q'.
 * @param w The positive integer 'ω'.
 */
struct Channel {
  uint64_t p;
  uint64_t q;
  uint64_t w;
};

/**
 * @brief Initialize an arithmetic channel.
 *
 * This function initializes an arithmetic channel with the provided parameters.
 *
 * @param channel Pointer to the arithmetic channel structure to be initialized.
 * @param p The positive integer 'p'.
 * @param q The positive integer 'q'.
 * @param w The positive integer 'ω'.
 *
 * @return 0 if successful.
 */
int init_channel(struct Channel *, uint64_t p, uint64_t q, uint64_t w);
